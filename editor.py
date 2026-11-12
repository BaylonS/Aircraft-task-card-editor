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
    if not tail or not description:
        raise ValueError('Enter both a tail number and a task / location description.')
    if len(tail) > 30 or '\n' in tail:
        raise ValueError('Tail number must be one line, at most 30 characters.')
    if len(description) > 2000:
        raise ValueError('Description must be at most 2,000 characters.')
    if any(ord(c) < 32 and c not in '\n\t' for c in tail + description):
        raise ValueError('Text contains an unsupported control character.')
    return tail, description


def header_areas(page):
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
    for area in (tail,desc):
        if page.get_text('words',clip=area) or any(area.intersects(fitz.Rect(i['bbox'])) for i in page.get_image_info()):
            raise ValueError('A target header area already contains text or an image. Use the original blank PDF.')
        if any(area.intersects(a.rect) for a in (page.annots() or [])) or any(area.intersects(w.rect) for w in (page.widgets() or [])):
            raise ValueError('A target area contains an annotation or form field. Use the original blank PDF.')
    return tail,desc


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


def fill_document(source, tail, description, tail_size=10, description_size=10):
    tail,description = validate(tail,description)
    sizes = validate_sizes(tail_size, description_size)
    doc = fitz.open(source)
    try:
        if doc.needs_pass:
            raise ValueError('Password-protected PDF: save an unlocked copy first.')
        if not doc.is_pdf or not len(doc):
            raise ValueError('The file is not a nonempty PDF.')
        if not doc.permissions & fitz.PDF_PERM_MODIFY:
            raise ValueError('This PDF does not allow modification.')
        for page in doc:
            try:
                areas = header_areas(page)
                for area,text,size,field in zip(areas,(tail,description),sizes,('Tail number','Description')):
                    # Match the reference baseline, wrapping only when necessary.
                    box = fitz.Rect(area.x0, max(area.y0,areas[0].y0+5),area.x1,area.y1)
                    alignment = 'center' if area == areas[1] else 'left'
                    content = f'<div style="text-align:{alignment}">'+html.escape(text).replace('\n','<br>')+'</div>'
                    spare,scale = page.insert_htmlbox(box,content,css=f'* {{font-family: sans-serif; font-size:{size:g}pt; color:black; margin:0; padding:0}}',scale_low=1)
                    if spare < 0:
                        raise ValueError(f'{field} will not fit at {size:g} pt. Choose a smaller size or shorten the entry.')
            except Exception as exc:
                raise ValueError(f'Page {page.number+1}: {exc}') from exc
        return doc
    except Exception:
        doc.close()
        raise


def save_copy(source, folder, tail, description, tail_size=10, description_size=10):
    with fill_document(source,tail,description,tail_size,description_size) as doc:
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
        self.geometry('800x650')
        self.minsize(650,550)
        self.files=[]
        self.events=queue.Queue()
        panel=ttk.Frame(self,padding=18); panel.pack(fill='both',expand=True)
        ttk.Label(panel,text='Aircraft Task Card Editor',font=('Segoe UI',20,'bold')).pack(anchor='w')
        ttk.Label(panel,text='Add black header text to every page. Original PDFs stay unchanged.').pack(anchor='w',pady=(4,14))
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
        ttk.Label(desc_heading,text='Task / location description').pack(side='left')
        ttk.Spinbox(desc_heading,from_=7,to=36,increment=1,textvariable=self.description_size,width=6).pack(side='right')
        ttk.Label(desc_heading,text='Text size (pt)  ').pack(side='right')
        self.desc=tk.Text(panel,height=4,wrap='word',font=('Segoe UI',11)); self.desc.pack(fill='x',pady=(3,10))
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
        return (*validate(self.tail.get(),self.desc.get('1.0','end')),
                *validate_sizes(self.tail_size.get(),self.description_size.get()))

    def preview(self):
        try:
            tail,desc,tail_size,description_size=self.inputs()
            i=next(iter(self.listbox.curselection()),0)
            doc=fill_document(self.files[i],tail,desc,tail_size,description_size)
        except Exception as exc:
            messagebox.showerror('Preview unavailable',str(exc)); return
        win=tk.Toplevel(self); win.title('Completed PDF preview'); win.geometry('850x800')
        bar=ttk.Frame(win); bar.pack(fill='x')
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
            tail,desc,tail_size,description_size=self.inputs()
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
                    target=save_copy(source,folder,tail,desc,tail_size,description_size); ok+=1
                    self.events.put(('log',f'Saved: {target}'))
                except Exception as exc:
                    self.events.put(('log',f'FAILED {Path(source).name}: {exc}'))
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
