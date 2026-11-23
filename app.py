import json
import sqlite3
import tkinter as tk
from datetime import date, datetime, time, timedelta
from tkinter import filedialog, messagebox, ttk
from uuid import uuid4

from planner import KINDS, ROOT, Store, event, stamp

DAYS = ("Thứ hai","Thứ ba","Thứ tư","Thứ năm","Thứ sáu","Thứ bảy","Chủ nhật")


def load_sample(s, path):
    doc = json.loads(path.read_text(encoding="utf-8-sig"))
    courses = doc["courses"]
    if not isinstance(courses,list) or not all(isinstance(x,str) and x.strip() for x in courses):
        raise ValueError("courses phải là danh sách tên môn.")
    for c in courses:
        if c not in s["courses"]:
            s["courses"].append(c)
    for source in doc["tasks"]:
        t = dict(source)
        k = t.pop("id")
        if not isinstance(k,str) or not k or k in s["tasks"]:
            raise ValueError(f"ID thiếu hoặc đã tồn tại: {k}")
        if "due" not in t:
            day = date.today() + timedelta(days=t.pop("days"))
            t["due"] = stamp(datetime.combine(day,time(22)))
        t.setdefault("deps",[])
        t["left"] = t["estimate"]
        s["tasks"][k] = t


class Form(tk.Toplevel):
    def __init__(self, parent, title, fields, submit):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.resizable(False,False)
        self.grab_set()
        self.values = []
        for i,(label,initial,options) in enumerate(fields):
            ttk.Label(self,text=label).grid(row=i,column=0,sticky="w",padx=12,pady=5)
            var = tk.StringVar(value=initial)
            control = (ttk.Combobox(self,values=options,state="readonly",textvariable=var,width=38)
                       if options is not None else ttk.Entry(self,textvariable=var,width=41))
            control.grid(row=i,column=1,padx=12,pady=5)
            self.values.append(var)
            if i == 0:
                control.focus_set()
        def save(*_):
            try:
                submit([v.get().strip() for v in self.values])
            except (ValueError,KeyError,TypeError,sqlite3.Error) as e:
                messagebox.showerror("Kiểm tra dữ liệu",str(e),parent=self)
                return
            self.destroy()
        ttk.Button(self,text="Lưu",command=save).grid(row=len(fields),column=1,sticky="e",padx=12,pady=12)
        self.bind("<Return>",save)
        self.bind("<Escape>",lambda _: self.destroy())


class App:
    def __init__(self, root, store):
        self.root,self.store = root,store
        root.title("Sổ học · Kế hoạch thích ứng")
        root.geometry("1180x690")
        root.minsize(810,510)
        top = ttk.Frame(root,padding=(16,12))
        top.pack(fill="x")
        ttk.Label(top,text="Sổ học",font=("Segoe UI",20,"bold")).pack(side="left")
        self.summary = ttk.Label(top)
        self.summary.pack(side="left",padx=24)
        book = ttk.Notebook(root)
        book.pack(fill="both",expand=True,padx=12,pady=6)
        self.tabs,self.tables = {},{}
        for key,title,columns,buttons in [
            ("plan","Lịch học",("Bắt đầu","Kết thúc","Môn","Việc","Phút","Lý do xếp lịch"),
             [("Ghi kết quả",lambda:self.log("plan")),("Bỏ buổi",self.skip),("Cập nhật",self.refresh)]),
            ("tasks","Việc học",("ID","Môn","Việc","Loại","Hạn","Dự kiến","Còn lại","Tiên quyết"),
             [("Thêm việc",lambda:self.task(False)),("Sửa việc",lambda:self.task(True)),("Ghi tự học",lambda:self.log("tasks")),("Xóa việc",self.delete_task),("Nạp ví dụ",lambda:self.import_file(True)),("Nhập JSON",lambda:self.import_file(False))]),
            ("courses","Môn học",("Tên môn","Số việc"),[("Thêm môn",lambda:self.course(False)),("Đổi tên",lambda:self.course(True)),("Xóa môn trống",self.delete_course)]),
            ("history","Nhật ký",("Ghi lúc","Việc","Buổi dự kiến","Trạng thái","Thực học","Còn lại lúc ghi"),[("Bổ sung buổi chưa ghi",lambda:self.log("history"))]),
            ("alerts","Cảnh báo",("Nội dung",),[])]:
            page = ttk.Frame(book,padding=8)
            book.add(page,text=title)
            bar = ttk.Frame(page)
            bar.pack(fill="x",pady=(0,8))
            for name,cb in buttons:
                ttk.Button(bar,text=name,command=lambda f=cb:self.guard(f)).pack(side="left",padx=2)
            body = ttk.Frame(page)
            body.pack(fill="both",expand=True)
            tree = ttk.Treeview(body,columns=columns,show="headings",selectmode="browse")
            for col in columns:
                tree.heading(col,text=col)
                tree.column(col,width=415 if col=="Lý do xếp lịch" else 180 if col in ("Việc","Môn") else 115,minwidth=55)
            for axis in ("x","y"):
                scroll = ttk.Scrollbar(body,orient="horizontal" if axis=="x" else "vertical",command=getattr(tree,axis+"view"))
                tree.configure(**{axis+"scrollcommand":scroll.set})
                scroll.grid(row=int(axis=="x"),column=int(axis=="y"),sticky="ew" if axis=="x" else "ns")
            tree.grid(row=0,column=0,sticky="nsew")
            body.columnconfigure(0,weight=1)
            body.rowconfigure(0,weight=1)
            self.tables[key] = tree
        footer = ttk.Frame(root,padding=10)
        footer.pack(fill="x")
        ttk.Button(footer,text="Giờ rảnh & giới hạn",command=lambda:self.guard(self.settings)).pack(side="left")
        self.hint = ttk.Label(footer)
        self.hint.pack(side="left",padx=12)
        self.refresh()
        self.timer = root.after(60000,self.tick)

    def tick(self):
        self.guard(self.refresh)
        self.timer = self.root.after(60000,self.tick)

    def guard(self,func):
        try:
            func()
        except (ValueError,TypeError,KeyError,AttributeError,OverflowError,OSError,sqlite3.Error) as e:
            messagebox.showerror("Sổ học",str(e),parent=self.root)

    def refresh(self, change=lambda s:None):
        s,alerts = self.store.update(change)
        self.state = s
        tasks = s["tasks"]
        rows = {k:[] for k in self.tables}
        for i,h in enumerate(s["sessions"]):
            t = tasks[h["task"]]
            rows["plan"].append((h["start"],(h["start"],h["end"],t["course"],t["name"],h["minutes"],h["reason"])))
        for k,t in tasks.items():
            rows["tasks"].append((k,(k,t["course"],t["name"],t["kind"],t["due"],t["estimate"],t["left"],", ".join(t["deps"]))))
        for c in s["courses"]:
            rows["courses"].append((c,(c,sum(t["course"]==c for t in tasks.values()))))
        for i,h in reversed(list(enumerate(s["history"]))):
            rows["history"].append((str(i),(h["at"],h["name"],h["start"],h["status"],h["actual"],h["remaining"])))
        rows["alerts"] = [(str(i),(v,)) for i,v in enumerate(alerts)]
        for k,items in rows.items():
            tree = self.tables[k]
            selected = tree.selection()
            tree.delete(*tree.get_children())
            for ident,values in items:
                tree.insert("","end",iid=ident,values=values)
            if selected and tree.exists(selected[0]):
                tree.selection_set(selected[0])
        actual = sum(h["actual"] for h in s["history"])
        done = sum(t["left"]==0 for t in tasks.values())
        self.summary.config(text=f"Hoàn thành {done}/{len(tasks)} việc     •     Đã học {actual} phút     •     Còn {sum(t['left'] for t in tasks.values())} phút     •     {len(alerts)} cảnh báo")
        self.hint.config(text="Bắt đầu ở Việc học → Nạp ví dụ, hoặc thêm môn của mày." if not tasks else f"{len(s['sessions'])} buổi trong kế hoạch 90 ngày · giờ địa phương")

    def selected(self,key):
        rows = self.tables[key].selection()
        if not rows:
            raise ValueError("Chọn một dòng trước.")
        return rows[0]

    def course(self,edit):
        old = self.selected("courses") if edit else None
        def save(v):
            name = v[0]
            def apply(s):
                if not name or name in s["courses"] and name != old:
                    raise ValueError("Tên môn trống hoặc đã tồn tại.")
                if edit:
                    s["courses"][s["courses"].index(old)] = name
                    for t in s["tasks"].values():
                        if t["course"]==old:
                            t["course"] = name
                else:
                    s["courses"].append(name)
            self.refresh(apply)
        Form(self.root,"Môn học",[("Tên môn",old or "",None)],save)

    def delete_course(self):
        c = self.selected("courses")
        def apply(s):
            if any(t["course"]==c for t in s["tasks"].values()):
                raise ValueError("Hãy chuyển các việc sang môn khác trước.")
            s["courses"].remove(c)
        if messagebox.askyesno("Xóa môn",f"Xóa {c}?"):
            self.refresh(apply)

    def task(self,edit):
        courses = self.state["courses"]
        if not courses:
            raise ValueError("Thêm môn trong thẻ Môn học trước.")
        k = self.selected("tasks") if edit else uuid4().hex[:8]
        t = self.state["tasks"].get(k,{})
        fields = [("Tên việc",t.get("name",""),None),("Môn",t.get("course",courses[0]),courses),
                  ("Loại",t.get("kind",KINDS[0]),KINDS),("Hạn YYYY-MM-DD HH:MM",t.get("due",stamp(datetime.combine(date.today()+timedelta(days=7),time(22)))),None),
                  ("Dự kiến ban đầu (phút)",t.get("estimate",60),None),("Ưu tiên 1–5",t.get("priority",3),None),
                  ("Độ khó 1–5",t.get("difficulty",3),None),("ID tiên quyết, cách bằng dấu phẩy",", ".join(t.get("deps",[])),None)]
        if edit:
            fields.append(("Khối lượng còn lại (phút)",t["left"],None))
        def save(v):
            item = dict(name=v[0],course=v[1],kind=v[2],due=v[3],estimate=int(v[4]),priority=int(v[5]),difficulty=int(v[6]),
                        deps=[x.strip() for x in v[7].split(",") if x.strip()],left=int(v[8] if edit else v[4]))
            self.refresh(lambda s:s["tasks"].update({k:item}))
        Form(self.root,"Việc học",fields,save)

    def delete_task(self):
        k = self.selected("tasks")
        def apply(s):
            if any(k in t["deps"] for t in s["tasks"].values()):
                raise ValueError("Gỡ việc này khỏi danh sách tiên quyết của các việc khác trước.")
            del s["tasks"][k]
        if messagebox.askyesno("Xóa việc","Xóa việc đã chọn? Nhật ký đã ghi vẫn được giữ."):
            self.refresh(apply)

    def session(self):
        start = self.selected("plan")
        return next(h for h in self.state["sessions"] if h["start"]==start)

    def skip(self):
        h = self.session()
        def apply(s):
            if h not in s["sessions"]:
                raise ValueError("Lịch đã đổi. Chọn lại buổi.")
            event(s,h,datetime.now(),0,s["tasks"][h["task"]]["left"],"Bỏ buổi")
            s["sessions"].remove(h)
        self.refresh(apply)

    def log(self,source):
        now = datetime.now()
        idx = None
        if source=="tasks":
            k = self.selected("tasks")
            h = dict(task=k,start=stamp(now),end=stamp(now),minutes=0)
        elif source=="history":
            idx = int(self.selected("history"))
            h = self.state["history"][idx]
            if h["status"]!="Chưa ghi nhận" or h["task"] not in self.state["tasks"]:
                raise ValueError("Chọn buổi chưa ghi nhận của việc còn tồn tại.")
        else:
            h = self.session()
            if h["start"] > stamp(now):
                raise ValueError("Buổi này chưa bắt đầu. Dùng Ghi tự học nếu đã học sớm.")
        k = h["task"]
        t = self.state["tasks"][k]
        def save(v):
            def apply(s):
                if idx is not None:
                    if s["history"][idx]["status"]!="Chưa ghi nhận":
                        raise ValueError("Buổi này đã được ghi.")
                    s["history"].pop(idx)
                if source=="plan":
                    if h not in s["sessions"]:
                        raise ValueError("Buổi đã đổi. Kiểm tra nhật ký.")
                    s["sessions"].remove(h)
                event(s,h,datetime.now(),int(v[0]),int(v[1]),"Đã ghi")
            self.refresh(apply)
        Form(self.root,t["name"],[("Thực học (phút)",h["minutes"],None),
             ("Ước lượng còn lại hiện tại (0 = xong)",max(0,t["left"]-h["minutes"]),None)],save)

    def import_file(self,sample):
        from pathlib import Path
        path = ROOT/"sample.json" if sample else filedialog.askopenfilename(filetypes=[("JSON","*.json")])
        if path:
            self.refresh(lambda s:load_sample(s,Path(path)))

    def settings(self):
        cfg = self.state["settings"]
        fields = [(d,w,None) for d,w in zip(DAYS,cfg["windows"])]
        fields += [("Tối đa phút học/ngày",cfg["cap"],None),("Tối đa phút/buổi",cfg["block"],None),
                   ("Nghỉ giữa buổi (phút)",cfg["rest"],None),("Ngày bận YYYY-MM-DD, cách dấu phẩy",", ".join(cfg["off"]),None)]
        def save(v):
            new = dict(windows=v[:7],cap=int(v[7]),block=int(v[8]),rest=int(v[9]),off=[x.strip() for x in v[10].split(",") if x.strip()])
            self.refresh(lambda s:s.update(settings=new))
        Form(self.root,"Giờ rảnh · ví dụ 08:00-10:00, 19:00-21:00",fields,save)


if __name__ == "__main__":
    root = tk.Tk()
    App(root,Store(ROOT/"data"))
    root.mainloop()

