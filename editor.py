"""Aircraft task-card header editor. Originals are never modified."""
from pathlib import Path
import html
import math
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pymupdf as fitz


def validate(tail, description):
    tail, description = tail.strip(), description.strip()
    if len(tail) > 30 or '\n' in tail:
        raise ValueError('Tail number must be one line, at most 30 characters.')
    if len(description) > 2000:
        raise ValueError('Description must be at most 2,000 characters.')
    if any(ord(c) < 32 and c not in '\n\t' for c in tail + description):
        raise ValueError('Text contains an unsupported control character.')
    return tail, description


def header_areas(page, active=(True, True)):
    """Use unrotated PDF coordinates; require real bordered, empty header cells."""
    bounds = page.rect * page.derotation_matrix
    hits = page.search_for('Tail Number:') or page.search_for('TAIL:')
    hits = [r for r in hits if r.y1 < bounds.height * .35 and r.x0 < bounds.width * .4]
    if len(hits) != 1:
        raise ValueError('Cannot identify a unique Tail Number: / TAIL: header. Scanned PDFs need OCR first.')
    label = hits[0]
    y = (label.y0 + label.y1) / 2
    vertical, horizontal = [], []
    for drawing in page.get_drawings():
        if drawing['type'] not in ('s', 'fs'):
            continue
        for item in drawing['items']:
            segments = []
            if item[0] == 'l':
                segments = [(item[1], item[2])]
            elif item[0] == 're':
                r = item[1]
                segments = [(r.tl,r.tr),(r.tr,r.br),(r.br,r.bl),(r.bl,r.tl)]
            for a,b in segments:
                if abs(a.x-b.x)<1 and min(a.y,b.y)-1 <= y <= max(a.y,b.y)+1:
                    vertical.append((a.x+b.x)/2)
                if abs(a.y-b.y)<1:
                    horizontal.append((min(a.x,b.x),max(a.x,b.x),(a.y+b.y)/2))
    xs = sorted(set(round(x,1) for x in vertical))
    left = [x for x in xs if x < label.x0+1]
    right = [x for x in xs if x > label.x1+4]
    if not left or len(right)<3:
        raise ValueError('Header cell borders could not be found safely.')
    def cell(x0,x1):
        ys = [v for a,b,v in horizontal if a <= x0+2 and b >= x1-2]
        above, below = [v for v in ys if v < label.y0], [v for v in ys if v > label.y1]
        if not above or not below:
            raise ValueError('Header top/bottom borders could not be found.')
        r = fitz.Rect(x0+4,max(above)+3,x1-4,min(below)-3)
        if r.height < 10 or r.height > bounds.height*.12:
            raise ValueError('Unexpected header height; no changes saved.')
        return r
    tail = cell(max(left), min(right))
    tail.x0 = label.x1 + 9
    desc = cell(xs[-2],xs[-1])
    if desc.x0 < bounds.width*.6 or tail.width<15:
        raise ValueError('Unexpected header layout; no changes saved.')
    for area,enabled in zip((tail,desc),active):
        if not enabled:
            continue
        if page.get_text('words',clip=area) or any(area.intersects(fitz.Rect(i['bbox'])) for i in page.get_image_info()):
            raise ValueError('A target header area already contains text or an image. Use the original blank PDF.')
        if any(area.intersects(a.rect) for a in (page.annots() or [])) or any(area.intersects(w.rect) for w in (page.widgets() or [])):
            raise ValueError('A target area contains an annotation or form field. Use the original blank PDF.')
    return tail,desc


def weekly_label(page, text):
    bounds = page.rect * page.derotation_matrix
    matches = page.search_for(text, clip=fitz.Rect(0,0,bounds.width*.3,bounds.height*.2))
    # search_for also matches substrings such as STA in INSTALL.
    words=page.get_text('words')
    matches=[r for r in matches if ' '.join(w[4] for w in words
             if fitz.Rect(w[:4]).intersects(r)) .casefold()==text.casefold()]
    if len(matches)>1:
        raise ValueError(f'Ambiguous {text} header.')
    return matches[0] if matches else None


def weekly_area(page, label, allow_dash=False):
    """Locate the bordered cell containing a small label; write below it."""
    cx,cy=(label.x0+label.x1)/2,(label.y0+label.y1)/2
    vertical,horizontal=[],[]
    for drawing in page.get_drawings():
        if drawing['type'] not in ('s','fs'): continue
        for item in drawing['items']:
            segments=[]
            if item[0]=='l': segments=[(item[1],item[2])]
            elif item[0]=='re':
                r=item[1]; segments=[(r.tl,r.tr),(r.tr,r.br),(r.br,r.bl),(r.bl,r.tl)]
            for a,b in segments:
                if abs(a.x-b.x)<1 and min(a.y,b.y)-1<=cy<=max(a.y,b.y)+1:
                    vertical.append((a.x+b.x)/2)
                if abs(a.y-b.y)<1 and min(a.x,b.x)-1<=cx<=max(a.x,b.x)+1:
                    horizontal.append((a.y+b.y)/2)
    left=[x for x in vertical if x<label.x0]
    right=[x for x in vertical if x>label.x1]
    top=[y for y in horizontal if y<label.y0]
    bottom=[y for y in horizontal if y>label.y1]
    if not all((left,right,top,bottom)):
        raise ValueError('Cannot identify the work-card header cell borders.')
    area=fitz.Rect(max(left)+3,label.y1+.3,min(right)-3,min(bottom)-.7)
    if area.width<20 or area.height<7 or min(bottom)-max(top)>60:
        raise ValueError('Unexpected work-card header cell size.')
    placeholders=[]
    for word in page.get_text('words'):
        r=fitz.Rect(word[:4])
        if r.intersects(area):
            if allow_dash and word[4]=='-': placeholders.append(r)
            else: raise ValueError('A work-card target field already contains text. Use a blank original.')
    if any(area.intersects(fitz.Rect(i['bbox'])) for i in page.get_image_info()):
        raise ValueError('A work-card target field contains an image.')
    if any(area.intersects(a.rect) for a in (page.annots() or [])) or any(area.intersects(w.rect) for w in (page.widgets() or [])):
        raise ValueError('A work-card target field contains an annotation or form field.')
    return area,placeholders


def write_weekly(page, tail, date, station, tail_size):
    for label_text,text,size in [('TAIL NO.',tail,tail_size),('DATE',date,8),('STA',station,8)]:
        if not text: continue
        label=weekly_label(page,label_text)
        if label is None: continue  # Continuation pages only have TAIL NO.
        area,placeholders=weekly_area(page,label,allow_dash=label_text!='TAIL NO.')
        if placeholders and any(a.type[0]==fitz.PDF_ANNOT_REDACT for a in (page.annots() or [])):
            raise ValueError('This page has pending redactions. Use a clean original before replacing header dashes.')
        for r in placeholders:
            page.add_redact_annot(r,fill=False,cross_out=False)
        if placeholders:
            page.apply_redactions(images=0,graphics=0)
        spare,_=page.insert_htmlbox(area,'<div>'+html.escape(text)+'</div>',
            css=f'* {{font-family:sans-serif; font-size:{size:g}pt; line-height:0.9; color:black; text-align:center; margin:0; padding:0}}',scale_low=1)
        if spare<0:
            raise ValueError(f'{label_text} will not fit at {size:g} pt. Shorten it or reduce the tail text size.')


def validate_sizes(tail_size, description_size):
    sizes = []
    for label, value in [('Tail number', tail_size), ('Description', description_size)]:
        try:
            size = float(value)
        except (TypeError, ValueError):
            raise ValueError(f'{label} text size must be a number from 7 to 36 points.') from None
        if not math.isfinite(size) or not 7 <= size <= 36:
            raise ValueError(f'{label} text size must be from 7 to 36 points.')
        sizes.append(size)
    return tuple(sizes)


def fill_document(source, tail, description, tail_size=10, description_size=10, date='', station=''):
    tail,description = validate(tail,description)
    sizes = validate_sizes(tail_size if tail else 10, description_size if description else 10)
    date,station=date.strip(),station.strip()
    for label,value,limit in [('Date',date,20),('Station',station,12)]:
        if len(value)>limit or any(ord(c)<32 for c in value):
            raise ValueError(f'{label} must be one line, at most {limit} characters.')
    doc = fitz.open(source)
    try:
        if doc.needs_pass:
            raise ValueError('Password-protected PDF: save an unlocked copy first.')
        if not doc.is_pdf or not len(doc):
            raise ValueError('The file is not a nonempty PDF.')
        if not doc.permissions & fitz.PDF_PERM_MODIFY:
            raise ValueError('This PDF does not allow modification.')
        has_weekly=any(weekly_label(p,'TAIL NO.') is not None for p in doc)
        changed=0
        notes=[]
        for page in doc:
            try:
                if not any((tail,description,date,station)):
                    continue
                if weekly_label(page,'TAIL NO.') is not None:
                    write_weekly(page,tail,date,station,sizes[0])
                    changed+=bool(tail or (date and weekly_label(page,'DATE')) or (station and weekly_label(page,'STA')))
                    continue
                # Only the recognized Allegiant cover sheet may be skipped.
                cover_text=page.get_text()
                if page.number==0 and has_weekly and all(t in cover_text for t in ('ALLEGIANT AIR Task Card','Task Card Description','Attachments:')):
                    notes.append('Cover sheet left unchanged.')
                    continue
                if not tail and not description:
                    # Date / Station apply only to the other work-card layout.
                    continue
                areas = header_areas(page,(bool(tail),bool(description)))
                for area,text,size,field in zip(areas,(tail,description),sizes,('Tail number','Description')):
                    if not text: continue
                    # Match the reference baseline, wrapping only when necessary.
                    box = fitz.Rect(area.x0, max(area.y0,areas[0].y0+5),area.x1,area.y1)
                    alignment = 'center' if area == areas[1] else 'left'
                    content = f'<div style="text-align:{alignment}">'+html.escape(text).replace('\n','<br>')+'</div>'
                    spare,scale = page.insert_htmlbox(box,content,css=f'* {{font-family: sans-serif; font-size:{size:g}pt; color:black; margin:0; padding:0}}',scale_low=1)
                    if spare < 0:
                        raise ValueError(f'{field} will not fit at {size:g} pt. Choose a smaller size or shorten the entry.')
                changed+=1
            except Exception as exc:
                raise ValueError(f'Page {page.number+1}: {exc}') from exc
        if has_weekly and description:
            notes.append('Description applies only to Airbus Tail Number: headers; omitted on TAIL NO. work-card pages.')
        notes.append(f'{changed} page(s) updated; blank entries leave existing fields unchanged.')
        doc.editor_notes=notes
        return doc
    except Exception:
        doc.close()
        raise


def save_copy(source, folder, tail, description, tail_size=10, description_size=10, date='', station=''):
    with fill_document(source,tail,description,tail_size,description_size,date,station) as doc:
        data = doc.tobytes(garbage=3,deflate=True)
    # Exclusive creation also protects against races and duplicate input names.
    base = Path(folder) / (Path(source).stem + '_completed.pdf')
    for number in range(10000):
        target = base if number == 0 else base.with_name(f'{base.stem}_{number}{base.suffix}')
        try:
            stream = target.open('xb')
        except FileExistsError:
            continue
        try:
            with stream:
                stream.write(data)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return target
    raise ValueError('Too many existing output copies.')


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Aircraft Task Card Editor')
        self.geometry('800x770')
        self.minsize(650,700)
        self.files=[]
        self.events=queue.Queue()
        panel=ttk.Frame(self,padding=18); panel.pack(fill='both',expand=True)
        ttk.Label(panel,text='Aircraft Task Card Editor',font=('Segoe UI',20,'bold')).pack(anchor='w')
        ttk.Label(panel,text='Detects both card layouts. All entries are optional; blank means leave unchanged.').pack(anchor='w',pady=(4,14))
        buttons=ttk.Frame(panel); buttons.pack(fill='x')
        ttk.Button(buttons,text='Add PDFs…',command=self.add).pack(side='left')
        ttk.Button(buttons,text='Remove selected',command=self.remove).pack(side='left',padx=8)
        self.listbox=tk.Listbox(panel,height=6,selectmode='extended',exportselection=False)
        self.listbox.pack(fill='x',pady=8)
        self.tail_size=tk.StringVar(value='10')
        self.description_size=tk.StringVar(value='10')
        tail_heading=ttk.Frame(panel); tail_heading.pack(fill='x')
        ttk.Label(tail_heading,text='Aircraft tail number').pack(side='left')
        ttk.Spinbox(tail_heading,from_=7,to=36,increment=1,textvariable=self.tail_size,width=6).pack(side='right')
        ttk.Label(tail_heading,text='Text size (pt)  ').pack(side='right')
        self.tail=ttk.Entry(panel); self.tail.pack(fill='x',pady=(3,10))
        desc_heading=ttk.Frame(panel); desc_heading.pack(fill='x')
        ttk.Label(desc_heading,text='Task / location description (Airbus layout only)').pack(side='left')
        ttk.Spinbox(desc_heading,from_=7,to=36,increment=1,textvariable=self.description_size,width=6).pack(side='right')
        ttk.Label(desc_heading,text='Text size (pt)  ').pack(side='right')
        self.desc=tk.Text(panel,height=4,wrap='word',font=('Segoe UI',11)); self.desc.pack(fill='x',pady=(3,10))
        details=ttk.Frame(panel); details.pack(fill='x',pady=(0,10))
        details.columnconfigure(0,weight=1); details.columnconfigure(1,weight=1)
        ttk.Label(details,text='Date (optional, e.g. 11/12/2026)').grid(row=0,column=0,sticky='w')
        ttk.Label(details,text='Station / STA (optional, e.g. LAS)').grid(row=0,column=1,sticky='w',padx=(12,0))
        self.date=ttk.Entry(details); self.date.grid(row=1,column=0,sticky='ew',pady=3)
        self.station=ttk.Entry(details); self.station.grid(row=1,column=1,sticky='ew',pady=3,padx=(12,0))
        ttk.Label(panel,text='Date and Station: TAIL NO. work cards only, 8 pt. Cover pages stay unchanged.').pack(anchor='w')
        ttk.Label(panel,text='Output folder').pack(anchor='w')
        row=ttk.Frame(panel); row.pack(fill='x')
        self.folder=tk.StringVar(value=str(Path.home()/'Documents'/'Completed Task Cards'))
        ttk.Entry(row,textvariable=self.folder).pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='Browse…',command=self.browse).pack(side='left',padx=(8,0))
        self.actions=ttk.Frame(panel); self.actions.pack(fill='x',pady=14)
        self.preview_button=ttk.Button(self.actions,text='Preview selected PDF',command=self.preview); self.preview_button.pack(side='left')
        self.save_button=ttk.Button(self.actions,text='Create completed copies',command=self.run); self.save_button.pack(side='right')
        self.status=tk.Text(panel,height=7,wrap='word',state='disabled',font=('Segoe UI',10)); self.status.pack(fill='both',expand=True)
        self.after(100,self.poll)

    def log(self,text):
        self.status.configure(state='normal'); self.status.insert('end',text+'\n'); self.status.see('end'); self.status.configure(state='disabled')

    def add(self):
        for p in filedialog.askopenfilenames(filetypes=[('PDF files','*.pdf')]):
            if p not in self.files:
                self.files.append(p); self.listbox.insert('end',p)

    def remove(self):
        for i in reversed(self.listbox.curselection()):
            self.files.pop(i); self.listbox.delete(i)

    def browse(self):
        p=filedialog.askdirectory()
        if p: self.folder.set(p)

    def inputs(self):
        if not self.files: raise ValueError('Add at least one PDF.')
        tail,desc=validate(self.tail.get(),self.desc.get('1.0','end'))
        return (tail,desc,*validate_sizes(self.tail_size.get() if tail else 10,
                self.description_size.get() if desc else 10),self.date.get(),self.station.get())

    def preview(self):
        try:
            values=self.inputs()
            i=next(iter(self.listbox.curselection()),0)
            doc=fill_document(self.files[i],*values)
        except Exception as exc:
            messagebox.showerror('Preview unavailable',str(exc)); return
        win=tk.Toplevel(self); win.title('Completed PDF preview'); win.geometry('850x800')
        bar=ttk.Frame(win); bar.pack(fill='x')
        ttk.Label(win,text='\n'.join(doc.editor_notes),wraplength=800).pack(fill='x')
        number=tk.IntVar(value=1)
        label=ttk.Label(bar); label.pack(side='left',padx=12)
        canvas=tk.Canvas(win,bg='#777'); canvas.pack(fill='both',expand=True)
        def draw(delta=0):
            number.set(max(1,min(len(doc),number.get()+delta)))
            page=doc[number.get()-1]; scale=min(max(canvas.winfo_width()-20,100)/page.rect.width,max(canvas.winfo_height()-20,100)/page.rect.height)
            pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False)
            canvas.photo=tk.PhotoImage(data=pix.tobytes('ppm'))
            canvas.delete('all'); canvas.create_image(10,10,anchor='nw',image=canvas.photo)
            label.configure(text=f'Page {number.get()} of {len(doc)}')
        ttk.Button(bar,text='Previous',command=lambda:draw(-1)).pack(side='left')
        ttk.Button(bar,text='Next',command=lambda:draw(1)).pack(side='left')
        canvas.bind('<Configure>',lambda e:draw())
        win.protocol('WM_DELETE_WINDOW',lambda:(doc.close(),win.destroy()))

    def run(self):
        try:
            values=self.inputs()
            if not self.folder.get().strip(): raise ValueError('Choose an output folder.')
            folder=Path(self.folder.get()).expanduser(); folder.mkdir(parents=True,exist_ok=True)
        except Exception as exc:
            messagebox.showerror('Check entries',str(exc)); return
        files=list(self.files)
        self.save_button.configure(state='disabled'); self.preview_button.configure(state='disabled')
        def worker():
            ok=0
            for source in files:
                try:
                    target=save_copy(source,folder,*values); ok+=1
                    self.events.put(('log',f'Saved: {target}'))
                except Exception as exc:
                    self.events.put(('log',f'FAILED {Path(source).name}: {exc}'))
            self.events.put(('log','Date / Station apply only where those headers exist. Description applies only to the Airbus layout. Blank entries leave fields unchanged.'))
            self.events.put(('done',f'Finished: {ok} saved, {len(files)-ok} failed.'))
        threading.Thread(target=worker,daemon=True).start()

    def poll(self):
        while not self.events.empty():
            kind,text=self.events.get(); self.log(text)
            if kind=='done':
                self.save_button.configure(state='normal'); self.preview_button.configure(state='normal')
                messagebox.showinfo('Batch complete',text)
        self.after(100,self.poll)


if __name__=='__main__':
    App().mainloop()
