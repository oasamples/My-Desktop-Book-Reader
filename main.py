import io
import json
import queue
import re
import threading
import time
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
import urllib.error
import urllib.parse
import urllib.request

# Dynamic PIL Import handling
try:
    from PIL import Image, ImageTk
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False


class ModernBookReaderApp:

    def __init__(self, root):
        self.root = root
        self.root.title("My Desktop Book Reader")
        self.root.geometry("1100x800")
        self.root.configure(bg="#ffffff")

        # Balanced Quadratic Color Scheme
        self.colors = {
            "bg_main": "#ffffff",
            "bg_sidebar": "#f8f9fa",
            "accent": "#5b21b6",          # Primary: Deep Purple
            "accent_hover": "#4c1d95",    # Darker Purple
            "secondary": "#0f766e",       # Secondary: Soft Teal
            "tertiary": "#c2410c",        # Tertiary: Warm Coral
            "quaternary": "#b45309",      # Quaternary: Golden Sand
            "text_dark": "#1e293b",
            "text_muted": "#64748b",
            "border": "#e2e8f0",
            "paper": "#fbfaf7",
            "scroll_thumb": "#cbd5e1",    # Modern Scrollbar Thumb Gray
            "scroll_hover": "#94a3b8"     # Modern Scrollbar Hover Gray
        }

        self.headers = {
            "User-Agent": "LuminaReaderPublicDomainBot/1.0 (educational desktop reading app)"
        }
        self.chapter_indices = {}
        
        # Async search/state variables with race condition protections
        self.search_debounce_task = None
        self.search_counter = 0  
        self.api_queue = queue.Queue()
        self.current_suggestions = {}  
        self.selected_gutenberg_id = None
        self.selected_cover_id = None
        self.tk_cover_img = None

        self.configure_styles()
        self.create_layout()
        
        # Start the background API polling queue listener
        self.process_api_queue()

    def configure_styles(self):
        self.style = ttk.Style()
        self.style.theme_use("clam")
        
        # --- TRUE ROUNDED BUTTON STYLING ---
        self.style.configure(
            "Modern.TButton",
            background=self.colors["accent"],
            foreground="white",
            font=("Helvetica", 10, "bold"),
            borderwidth=0,
            focuscolor="none",
            padding=(20, 8)
        )
        # Force clam to render rounded border corners
        self.style.layout("Modern.TButton", [
            ('Button.border', {'sticky': 'nswe', 'border': '1', 'children': [
                ('Button.focus', {'sticky': 'nswe', 'children': [
                    ('Button.padding', {'sticky': 'nswe', 'children': [
                        ('Button.label', {'sticky': 'nswe'})
                    ]})
                ]})
            ]})
        ])
        
        self.style.map(
            "Modern.TButton",
            background=[("active", self.colors["accent_hover"])]
        )
        self.style.configure("TPanedwindow", background=self.colors["border"])

        # --- MODERN STREAMLINED SCROLLBAR STYLING ---
        # Strip arrows and create a minimalist layout
        self.style.layout("Modern.Vertical.TScrollbar", [
            ('Scrollbar.trough', {'sticky': 'ns', 'children': [
                ('Scrollbar.thumb', {'sticky': 'nswe'})
            ]})
        ])
        
        self.style.configure(
            "Modern.Vertical.TScrollbar",
            troughcolor=self.colors["bg_sidebar"],
            background=self.colors["scroll_thumb"],
            borderwidth=0,
            arrowsize=0,
            gripcount=0
        )
        
        self.style.map(
            "Modern.Vertical.TScrollbar",
            background=[("active", self.colors["scroll_hover"])]
        )

    def create_layout(self):
        # --- Top Navigation/Search Header ---
        header_bar = tk.Frame(self.root, bg=self.colors["bg_main"], bd=0)
        header_bar.pack(fill="x", side="top", padx=30, pady=(20, 15))

        brand_label = tk.Label(
            header_bar,
            text="My Desktop Book Reader",
            font=("Helvetica", 16, "bold"),
            bg=self.colors["bg_main"],
            fg=self.colors["text_dark"]
        )
        brand_label.pack(side="left")

        controls_frame = tk.Frame(header_bar, bg=self.colors["bg_main"])
        controls_frame.pack(side="right")

        # --- RE-ENGINEERED ROUNDED & PADDED SEARCH BAR ---
        search_capsule = tk.Frame(
            controls_frame,
            bg=self.colors["bg_sidebar"],
            bd=1,
            highlightthickness=0
        )
        search_capsule.pack(side="left", padx=(15, 10))

        self.search_entry = tk.Entry(
            search_capsule,
            font=("Helvetica", 11),
            width=38,
            bg=self.colors["bg_sidebar"],
            fg=self.colors["text_dark"],
            bd=0, 
            relief="flat",
            highlightthickness=0
        )
        self.search_entry.pack(side="left", padx=(12, 12), pady=6, ipady=2)
        self.search_entry.insert(0, "Type to search classics (e.g., Dracula)...")
        
        self.search_entry.bind("<KeyRelease>", self.on_search_key_release)
        self.search_entry.bind("<FocusIn>", lambda e: self.search_entry.delete(0, tk.END) if self.search_entry.get().startswith("Type to") else None)

        self.btn_load = ttk.Button(
            controls_frame, 
            text="Open Book", 
            style="Modern.TButton", 
            command=self.fetch_book
        )
        self.btn_load.pack(side="left")

        divider = tk.Frame(self.root, height=1, bg=self.colors["border"])
        divider.pack(fill="x", padx=30)

        # --- Main Split Content Panels Panel Workspace ---
        self.workspace = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        self.workspace.pack(fill="both", expand=True, padx=30, pady=20)

        # Left Column Frame: Cover Profile + Table of Contents
        self.sidebar = tk.Frame(self.workspace, bg=self.colors["bg_sidebar"], width=260)
        self.sidebar.pack_propagate(False)

        # Smooth Embedded Cover Art Component Card
        self.cover_frame = tk.Frame(self.sidebar, bg=self.colors["bg_sidebar"], height=280)
        self.cover_frame.pack(fill="x", padx=20, pady=(20, 0))
        self.cover_frame.pack_propagate(False)

        self.cover_canvas = tk.Canvas(
            self.cover_frame, 
            bg=self.colors["border"], 
            bd=0, 
            highlightthickness=0
        )
        self.cover_canvas.pack(fill="both", expand=True)
        self.reset_cover_placeholder("No Book Loaded")

        lbl_toc = tk.Label(
            self.sidebar,
            text="TABLE OF CONTENTS",
            font=("Helvetica", 9, "bold"),
            bg=self.colors["bg_sidebar"],
            fg=self.colors["quaternary"],
            anchor="w"
        )
        lbl_toc.pack(fill="x", padx=20, pady=(20, 10)) 

        # Container for the Chapter Listbox + Modern Scrollbar
        toc_scroll_frame = tk.Frame(self.sidebar, bg=self.colors["bg_sidebar"])
        toc_scroll_frame.pack(fill="both", expand=True, pady=(0, 20), padx=15)
        
        # FIX: Pack layout elements carefully so listbox doesn't stomp out scrollbar
        toc_scrollbar = ttk.Scrollbar(
            toc_scroll_frame, 
            orient="vertical", 
            command=self.chapter_listbox.yview if hasattr(self, 'chapter_listbox') else None,
            style="Modern.Vertical.TScrollbar"
        )
        toc_scrollbar.pack(side="right", fill="y")

        self.chapter_listbox = tk.Listbox(
            toc_scroll_frame,
            font=("Helvetica", 10),
            bg=self.colors["bg_sidebar"],
            fg=self.colors["text_dark"],
            relief="flat",
            bd=0,
            highlightthickness=0,
            selectbackground=self.colors["border"],
            selectforeground=self.colors["accent"],
            activestyle="none",
            yscrollcommand=toc_scrollbar.set
        )
        self.chapter_listbox.pack(side="left", fill="both", expand=True)
        toc_scrollbar.config(command=self.chapter_listbox.yview)
        self.chapter_listbox.bind("<<ListboxSelect>>", self.on_chapter_click)

        # Right Column Frame: E-Reading Typography Canvas
        view_container = tk.Frame(self.workspace, bg=self.colors["paper"])

        # FIX: Pack the scrollbar FIRST to ensure it renders on screen without being shoved out
        scrollbar = ttk.Scrollbar(
            view_container, 
            orient="vertical", 
            style="Modern.Vertical.TScrollbar"
        )
        scrollbar.pack(side="right", fill="y")

        self.book_display = tk.Text(
            view_container,
            wrap="word",
            font=("Georgia", 13),
            bg=self.colors["paper"],
            fg=self.colors["text_dark"],
            relief="flat",
            bd=0,
            padx=45,
            pady=40,
            spacing1=6,
            spacing2=4,
            spacing3=6,
            yscrollcommand=scrollbar.set,
            cursor="arrow"
        )
        self.book_display.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.book_display.yview)

        self.workspace.add(self.sidebar, weight=1)
        self.workspace.add(view_container, weight=4)

        self.book_display.tag_config("status", font=("Helvetica", 12, "italic"), foreground=self.colors["text_muted"])
        
        # Word Lookup Feature
        self.book_display.bind("<Button-3>", self.show_context_menu)
        self.book_display.bind("<Button-2>", self.show_context_menu)
        self.context_menu = tk.Menu(self.root, tearoff=0, bg="white", fg=self.colors["text_dark"], relief="flat")

        # Autocomplete Dynamic Suggestions Overlay List Window
        self.popup_suggestions = tk.Listbox(
            self.root,
            font=("Helvetica", 10),
            bg="#ffffff",
            fg=self.colors["text_dark"],
            bd=1,
            relief="solid",
            highlightthickness=0,
            selectbackground=self.colors["border"],
            selectforeground=self.colors["accent"],
            activestyle="none"
        )
        self.popup_suggestions.bind("<<ListboxSelect>>", self.on_suggestion_select)

    def reset_cover_placeholder(self, text_string):
        self.cover_canvas.delete("all")
        self.cover_canvas.create_rectangle(0, 0, 260, 280, fill="#f1f5f9", outline="")
        self.cover_canvas.create_text(
            110, 140, 
            text=text_string, 
            fill=self.colors["text_muted"], 
            font=("Helvetica", 10, "italic"),
            justify="center"
        )

    # --- Asynchronous Open Library Auto-Suggestion Engine ---
    def on_search_key_release(self, event):
        if event.keysym in ("Up", "Down", "Return", "Escape"):
            return 

        query = self.search_entry.get().strip()
        if len(query) < 3 or query.startswith("Type to"):
            self.hide_suggestions_popup()
            self.search_entry.config(bg=self.colors["bg_sidebar"])
            return

        self.search_counter += 1
        current_token = self.search_counter

        self.search_entry.config(bg="#eff6ff") 
        self.show_suggestions_popup(["Searching Open Library..."])

        if self.search_debounce_task:
            self.root.after_cancel(self.search_debounce_task)

        self.search_debounce_task = self.root.after(
            300, 
            lambda: self.launch_api_worker(query, current_token)
        )

    def launch_api_worker(self, query, token):
        thread = threading.Thread(
            target=self.async_open_library_query, 
            args=(query, token), 
            daemon=True
        )
        thread.start()

    def async_open_library_query(self, query, token):
        encoded_query = urllib.parse.quote_plus(query)
        api_url = f"https://openlibrary.org/search.json?q={encoded_query}&fields=title,author_name,id_project_gutenberg,cover_i&limit=8"
        
        try:
            req = urllib.request.Request(api_url, headers=self.headers)
            with urllib.request.urlopen(req, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                
            results = []
            for doc in payload.get("docs", []):
                gutenberg_ids = doc.get("id_project_gutenberg", [])
                if gutenberg_ids:
                    title = doc.get("title", "Unknown Title")
                    authors = doc.get("author_name", ["Unknown Author"])
                    cover_id = doc.get("cover_i", None)
                    display_name = f"{title} — {authors[0]}"
                    results.append((display_name, gutenberg_ids[0], cover_id))
            
            self.api_queue.put(("SEARCH_SUCCESS", (results, token)))
        except Exception:
            self.api_queue.put(("SEARCH_ERROR", ([], token)))

    def process_api_queue(self):
        try:
            while True:
                queue_data = self.api_queue.get_nowait()
                status = queue_data[0]
                payload = queue_data[1]

                if status == "COVER_SUCCESS":
                    self.display_cover_image(payload)
                    continue
                elif status == "COVER_FAIL":
                    continue

                data, token = payload

                if token != self.search_counter:
                    continue

                self.search_entry.config(bg=self.colors["bg_sidebar"])
                
                if status == "SEARCH_SUCCESS":
                    if data:
                        self.current_suggestions = {name: {"g_id": gid, "cover_id": cid} for name, gid, cid in data}
                        self.show_suggestions_popup(list(self.current_suggestions.keys()))
                    else:
                        self.show_suggestions_popup(["No matching public domain books found"])
                        
                elif status == "SEARCH_ERROR":
                    self.show_suggestions_popup(["Search failed. Check your connection."])
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self.process_api_queue)

    def show_suggestions_popup(self, list_items):
        self.popup_suggestions.delete(0, tk.END)
        for item in list_items:
            self.popup_suggestions.insert(tk.END, f"  {item}")

        x = self.search_entry.winfo_rootx() - self.root.winfo_rootx()
        y = (self.search_entry.winfo_rooty() - self.root.winfo_rooty()) + self.search_entry.winfo_height()
        width = self.search_entry.winfo_width()

        self.popup_suggestions.place(x=x, y=y, width=width, height=180)
        self.popup_suggestions.lift()

    def hide_suggestions_popup(self):
        self.popup_suggestions.place_forget()

    def on_suggestion_select(self, event):
        try:
            selection = self.popup_suggestions.curselection()
            if not selection:
                return
            
            chosen_text = self.popup_suggestions.get(selection[0]).strip()
            
            if chosen_text.startswith("Searching") or chosen_text.startswith("No matching") or chosen_text.startswith("Search failed"):
                return

            selection_info = self.current_suggestions.get(chosen_text)
            if selection_info:
                self.selected_gutenberg_id = selection_info["g_id"]
                self.selected_cover_id = selection_info["cover_id"]
            
            self.search_entry.delete(0, tk.END)
            self.search_entry.insert(0, chosen_text)
            self.hide_suggestions_popup()
        except Exception:
            pass

    # --- Async Background Cover Art Downloader Pipeline ---
    def launch_cover_download(self, cover_id):
        if not cover_id:
            self.root.after(0, lambda: self.reset_cover_placeholder("No Cover Indexed"))
            return
        
        self.root.after(0, lambda: self.reset_cover_placeholder("Loading Cover..."))
        thread = threading.Thread(target=self.async_cover_fetch, args=(cover_id,), daemon=True)
        thread.start()

    def async_cover_fetch(self, cover_id):
        cover_url = f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg"
        try:
            req = urllib.request.Request(cover_url, headers=self.headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                img_bytes = response.read()
            self.api_queue.put(("COVER_SUCCESS", img_bytes))
        except Exception:
            self.api_queue.put(("COVER_FAIL", None))

    def display_cover_image(self, img_bytes):
        if not HAS_PILLOW:
            self.reset_cover_placeholder("Install Pillow package\nfor image cover view")
            return

        try:
            image = Image.open(io.BytesIO(img_bytes))
            
            if hasattr(Image, 'Resampling') and hasattr(Image.Resampling, 'LANCEZOS'):
                resample_filter = Image.Resampling.LANCEZOS
            elif hasattr(Image, 'Resampling') and hasattr(Image.Resampling, 'ANTIALIAS'):
                resample_filter = Image.Resampling.ANTIALIAS  
            elif hasattr(Image, 'LANCEZOS'):
                resample_filter = Image.LANCEZOS
            elif hasattr(Image, 'ANTIALIAS'):
                resample_filter = Image.ANTIALIAS
            else:
                resample_filter = 0  

            image = image.resize((220, 280), resample_filter)
            self.tk_cover_img = ImageTk.PhotoImage(image)
            
            self.cover_canvas.delete("all")
            self.cover_canvas.create_image(0, 0, anchor="nw", image=self.tk_cover_img)
        except Exception as e:
            print('canvas_error:', e)
            self.reset_cover_placeholder("Cover Format Error")

    # --- Main Content/Text Retrieval Modules ---
    def fetch_book(self):
        if not self.selected_gutenberg_id:
            raw_entry = self.search_entry.get().strip()
            if not raw_entry or raw_entry.startswith("Type to"):
                return
            match = re.search(r'\d+', raw_entry)
            if match:
                self.selected_gutenberg_id = match.group()
                self.selected_cover_id = None
            else:
                messagebox.showinfo("Search Info", "Please click one of the dropdown matching title results options directly.")
                return

        book_id = self.selected_gutenberg_id
        self.launch_cover_download(self.selected_cover_id)

        self.book_display.config(state="normal")
        self.book_display.delete("1.0", tk.END)
        self.chapter_listbox.delete(0, tk.END)
        self.chapter_indices.clear()

        self.book_display.insert(tk.END, "Opening Project Gutenberg text stream channels...\n", "status")
        self.book_display.config(state="disabled")
        self.root.update_idletasks()

        text_url = f"https://www.gutenberg.org/files/{book_id}/{book_id}-0.txt"

        try:
            text_req = urllib.request.Request(text_url, headers=self.headers)
            with urllib.request.urlopen(text_req, timeout=15) as text_response:
                book_text = text_response.read().decode("utf-8", errors="ignore")

            self.update_book_display(book_text)
            self.generate_table_of_contents(book_text)

        except urllib.error.HTTPError as e:
            if e.code == 404:
                fallback_url = f"https://www.gutenberg.org/ebooks/{book_id}.txt.utf-8"
                try:
                    text_req = urllib.request.Request(fallback_url, headers=self.headers)
                    with urllib.request.urlopen(text_req, timeout=15) as text_response:
                        book_text = text_response.read().decode("utf-8", errors="ignore")
                    self.update_book_display(book_text)
                    self.generate_table_of_contents(book_text)
                    return
                except Exception:
                    pass
            self.update_book_display(f"Could not load book file (HTTP {e.code})")
        except Exception as e:
            self.update_book_display(f"Connection error breakdown: {e}")
        finally:
            self.selected_gutenberg_id = None

    def update_book_display(self, text):
        self.book_display.config(state="normal")
        self.book_display.delete("1.0", tk.END)
        self.book_display.insert(tk.END, text)
        self.book_display.config(state="disabled")
        self.book_display.see("1.0")
        
        # Force layout update so the scrollbar learns the true content height
        self.root.update_idletasks()

    def generate_table_of_contents(self, text):
        lines = text.splitlines()
        chapter_regexes = [
            r"^(CHAPTER\s+[IVXLCDM\d]+)", 
            r"^(Chapter\s+[IVXLCDM\d]+)", 
            r"^(STORY\s+[IVXLCDM\d]+)", 
            r"^(ACT\s+[IVXLCDM\d]+)"
        ]

        start_parsing_line = 0
        for line_num, line in enumerate(lines):
            if "*** START OF" in line.upper():
                start_parsing_line = line_num
                break
        if start_parsing_line == 0:
            start_parsing_line = min(150, len(lines))

        toc_end_line = start_parsing_line
        for line_num in range(start_parsing_line, min(start_parsing_line + 300, len(lines))):
            line_upper = lines[line_num].upper().strip()
            if line_upper in ["CONTENTS", "TABLE OF CONTENTS", "INDEX"]:
                toc_end_line = line_num + 60
                break

        search_start_point = max(start_parsing_line, toc_end_line)
        listbox_index = 0

        for line_num in range(search_start_point, len(lines)):
            cleaned_line = lines[line_num].strip()
            if len(cleaned_line) > 50 or len(cleaned_line) < 3:
                continue

            for regex in chapter_regexes:
                if re.match(regex, cleaned_line, re.IGNORECASE):
                    title = cleaned_line
                    if len(title) < 40 and line_num < len(lines) - 1:
                        next_line = lines[line_num + 1].strip()
                        if next_line and len(next_line) < 40 and not any(re.match(r, next_line, re.IGNORECASE) for r in chapter_regexes):
                            title += f" : {next_line}"

                    self.chapter_listbox.insert(tk.END, f"  {title}")
                    self.chapter_indices[listbox_index] = f"{line_num + 1}.0"
                    listbox_index += 1
                    break

        if listbox_index == 0:
            self.chapter_listbox.insert(tk.END, "  No structural chapters parsed.")

    def on_chapter_click(self, event):
        try:
            selection = self.chapter_listbox.curselection()
            if not selection:
                return
            idx = selection[0]
            text_target_index = self.chapter_indices.get(idx)
            if text_target_index:
                self.book_display.see(text_target_index)
                self.book_display.tag_remove("highlight", "1.0", tk.END)
                self.book_display.tag_add("highlight", text_target_index, f"{text_target_index} lineend")
                self.book_display.tag_config("highlight", background="#e2e8f0", foreground=self.colors["accent"])
        except Exception:
            pass

    # --- Dictionary Look-up Framework Modules ---
    def show_context_menu(self, event):
        click_index = self.book_display.index(f"@{event.x},{event.y}")
        try:
            start_idx = self.book_display.index(f"{click_index} wordstart")
            end_idx = self.book_display.index(f"{click_index} wordend")
            clicked_word = self.book_display.get(start_idx, end_idx).strip().strip(".,;:?!\"'()[]{}—-*_")
        except Exception:
            return

        if clicked_word and clicked_word.isalpha():
            self.context_menu.delete(0, tk.END)
            self.context_menu.add_command(
                label=f" Look up '{clicked_word}'",
                command=lambda: self.open_dictionary_window(clicked_word),
            )
            self.context_menu.post(event.x_root, event.y_root)

    def open_dictionary_window(self, word):
        dict_win = tk.Toplevel(self.root)
        dict_win.title(f"Definition: {word}")
        dict_win.geometry("460x500")
        dict_win.configure(bg=self.colors["bg_sidebar"])

        frame = tk.Frame(dict_win, bg=self.colors["bg_sidebar"], padx=20, pady=20)
        frame.pack(fill="both", expand=True)

        dict_text = tk.Text(
            frame, wrap="word", font=("Helvetica", 11), bg="white", relief="flat",
            bd=0, padx=15, pady=15, spacing1=4
        )
        dict_text.pack(fill="both", expand=True)

        dict_text.tag_config("word", font=("Helvetica", 20, "bold"), foreground=self.colors["text_dark"])
        dict_text.tag_config("phonetic", font=("Helvetica", 11, "italic"), foreground=self.colors["text_muted"])
        dict_text.tag_config("part_of_speech", font=("Helvetica", 10, "bold"), foreground=self.colors["secondary"])
        dict_text.tag_config("definition", font=("Helvetica", 11), foreground="#334155")
        dict_text.tag_config("example", font=("Helvetica", 10, "italic"), foreground="#0f766e")

        dict_text.insert(tk.END, f"Searching definitions for '{word}'...\n")
        dict_text.config(state="disabled")
        dict_win.update()

        api_url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word.lower()}"
        try:
            req = urllib.request.Request(api_url, headers=self.headers)
            with urllib.request.urlopen(req, timeout=8) as response:
                data = json.loads(response.read().decode("utf-8"))

            dict_text.config(state="normal")
            dict_text.delete("1.0", tk.END)

            for entry in data:
                head_word = entry.get("word", "").capitalize()
                phonetic = entry.get("phonetic", "")
                if not phonetic and entry.get("phonetics"):
                    for p in entry["phonetics"]:
                        if p.get("text"):
                            phonetic = p["text"]
                            break

                dict_text.insert(tk.END, f"{head_word}\n", "word")
                if phonetic:
                    dict_text.insert(tk.END, f"{phonetic}  ", "phonetic")
                dict_text.insert(tk.END, "\n" + "─" * 25 + "\n\n")

                for meaning in entry.get("meanings", []):
                    pos = meaning.get("partOfSpeech", "").upper()
                    dict_text.insert(tk.END, f" {pos}\n", "part_of_speech")
                    for i, d in enumerate(meaning.get("definitions", []), start=1):
                        defn = d.get("definition", "")
                        eg = d.get("example", "")
                        dict_text.insert(tk.END, f"  {i}. {defn}\n", "definition")
                        if eg:
                            dict_text.insert(tk.END, f"     \"{eg}\"\n", "example")
                    dict_text.insert(tk.END, "\n")

        except urllib.error.HTTPError as e:
            dict_text.config(state="normal")
            dict_text.delete("1.0", tk.END)
            dict_text.insert(tk.END, f"No dictionary entry found for '{word}'." if e.code == 404 else f"Server error (HTTP {e.code}).")
        except Exception:
            dict_text.config(state="normal")
            dict_text.delete("1.0", tk.END)
            dict_text.insert(tk.END, "Network link offline.")

        dict_text.config(state="disabled")


if __name__ == "__main__":
    root = tk.Tk()
    app = ModernBookReaderApp(root)
    root.mainloop()