import customtkinter as ctk
import psutil
import pyttsx3
import json
import threading
import time
import os
import sys
from typing import Optional, List, Dict

# --- Configuration & Constants ---
GAMES_FILE = "games.json"
THEME_COLOR = "#8A2BE2"  # BlueViolet
HOVER_COLOR = "#9400D3"  # DarkViolet
FONT_MAIN = "Roboto"
WINDOW_SIZE = "700x500"
APP_TITLE = "VR Club Timer"

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")  # Will override accent colors manually

# --- Managers ---

class GameManager:
    """Handles loading and saving game configurations."""
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.games: List[Dict[str, str]] = []
        self.load_games()

    def load_games(self):
        if not os.path.exists(self.filepath):
            self.create_default_file()
        
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                self.games = json.load(f)
        except Exception as e:
            print(f"Error loading games: {e}")
            self.games = []

    def create_default_file(self):
        defaults = [
            {"name": "Beat Saber", "process": "beat_saber.exe"},
            {"name": "Superhot VR", "process": "superhot.exe"},
            {"name": "Half-Life: Alyx", "process": "hl_alyx.exe"}
        ]
        self.save_games(defaults)

    def save_games(self, games: Optional[List[Dict[str, str]]] = None):
        if games is not None:
            self.games = games
        try:
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(self.games, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving games: {e}")

    def add_game(self, name: str, process: str):
        self.games.append({"name": name, "process": process})
        self.save_games()

    def get_game_process(self, game_name: str) -> Optional[str]:
        for game in self.games:
            if game["name"] == game_name:
                return game["process"]
        return None

    def get_game_names(self) -> List[str]:
        return [g["name"] for g in self.games]


class SoundManager:
    """Handles Text-to-Speech notifications."""
    def __init__(self):
        try:
            self.engine = pyttsx3.init()
            # Set properties if needed (e.g., rate, volume)
            self.engine.setProperty('rate', 150)
        except Exception as e:
            print(f"TTS Init Error: {e}")
            self.engine = None

    def speak(self, text: str):
        if self.engine:
            def _speak():
                try:
                    self.engine.say(text)
                    self.engine.runAndWait()
                except Exception as e:
                    print(f"TTS Speak Error: {e}")
            
            # TTS must run in its own thread to not block the timer/UI
            threading.Thread(target=_speak, daemon=True).start()
        else:
            print(f"[TTS DISABLED] {text}")


class ProcessManager:
    """Handles finding and killing game processes."""
    @staticmethod
    def kill_process(process_name: str) -> bool:
        killed = False
        print(f"Attempting to kill {process_name}...")
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                # Simple case-insensitive match
                if proc.info['name'] and proc.info['name'].lower() == process_name.lower():
                    proc.kill()
                    killed = True
                    print(f"Killed process: {proc.info['name']} (PID: {proc.info['pid']})")
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return killed


class TimerThread(threading.Thread):
    """Refined Timer Logic running in a separate thread."""
    def __init__(self, duration_minutes: int, on_tick, on_finish, on_warning, game_process: str):
        super().__init__(daemon=True)
        self.total_seconds = int(duration_minutes * 60)
        self.remaining_seconds = self.total_seconds
        self.on_tick = on_tick
        self.on_finish = on_finish
        self.on_warning = on_warning
        self.game_process = game_process
        
        self.running = False
        self.paused = False
        self._stop_event = threading.Event()
        self.warning_triggered = False

    def run(self):
        self.running = True
        while self.remaining_seconds > 0 and not self._stop_event.is_set():
            if self.paused:
                time.sleep(0.1)
                continue
            
            # Logic Check: 5 minute warning
            if self.remaining_seconds == 5 * 60 and not self.warning_triggered:
                self.on_warning()
                self.warning_triggered = True

            # Update UI
            self.on_tick(self.remaining_seconds, self.total_seconds)
            
            time.sleep(1)
            self.remaining_seconds -= 1

        if not self._stop_event.is_set():
            # Timer finished naturally
            self.on_tick(0, self.total_seconds)
            self.on_finish(self.game_process)
        
        self.running = False

    def pause(self):
        self.paused = not self.paused

    def add_time(self, minutes: int):
        self.remaining_seconds += minutes * 60
        self.total_seconds = max(self.total_seconds, self.remaining_seconds)
        # Reset warning if we added time above 5 mins
        if self.remaining_seconds > 5 * 60:
            self.warning_triggered = False

    def stop(self):
        self._stop_event.set()


# --- UI ---

class VRTimerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title(APP_TITLE)
        self.geometry(WINDOW_SIZE)
        
        # Managers
        self.game_manager = GameManager(GAMES_FILE)
        self.sound_manager = SoundManager()
        self.process_manager = ProcessManager()
        self.timer_thread: Optional[TimerThread] = None

        # Variables
        self.selected_game = ctk.StringVar()
        self.custom_time_var = ctk.StringVar(value="60")
        
        self._init_ui()

    def _init_ui(self):
        # Configure grid layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Tabview for separation of Control and Settings
        self.tabview = ctk.CTkTabview(self, fg_color="transparent")
        self.tabview.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        
        self.tab_timer = self.tabview.add("Панель управления")
        self.tab_settings = self.tabview.add("Настройки")

        self._build_timer_tab()
        self._build_settings_tab()

    def _build_timer_tab(self):
        self.tab_timer.grid_columnconfigure(0, weight=1)
        
        # 1. Game Selection
        self.lbl_game = ctk.CTkLabel(self.tab_timer, text="Выберите игру:", font=(FONT_MAIN, 16))
        self.lbl_game.grid(row=0, column=0, pady=(10, 5))
        
        game_names = self.game_manager.get_game_names()
        self.combo_games = ctk.CTkOptionMenu(
            self.tab_timer, 
            variable=self.selected_game, 
            values=game_names if game_names else ["Нет игр"],
            fg_color=THEME_COLOR,
            button_color=THEME_COLOR,
            button_hover_color=HOVER_COLOR
        )
        self.combo_games.grid(row=1, column=0, pady=5)
        if game_names:
            self.combo_games.set(game_names[0])

        # 2. Status Bar
        self.lbl_status = ctk.CTkLabel(self.tab_timer, text="Ожидание", text_color="gray", font=(FONT_MAIN, 14, "italic"))
        self.lbl_status.grid(row=2, column=0, pady=10)

        # 3. Timer Display (Big)
        self.lbl_time = ctk.CTkLabel(self.tab_timer, text="00:00:00", font=(FONT_MAIN, 60, "bold"))
        self.lbl_time.grid(row=3, column=0, pady=10)
        
        self.progress_bar = ctk.CTkProgressBar(self.tab_timer, orientation="horizontal", mode="determinate")
        self.progress_bar.grid(row=4, column=0, sticky="ew", padx=40, pady=10)
        self.progress_bar.set(0)
        self.progress_bar.configure(progress_color=THEME_COLOR)

        # 4. Quick Time Buttons
        self.frm_quick_buttons = ctk.CTkFrame(self.tab_timer, fg_color="transparent")
        self.frm_quick_buttons.grid(row=5, column=0, pady=10)
        
        btn_params = {"fg_color": "transparent", "border_width": 2, "border_color": THEME_COLOR, "text_color": "white", "hover_color": THEME_COLOR}
        
        ctk.CTkButton(self.frm_quick_buttons, text="15 мин", command=lambda: self.start_timer(15), **btn_params).pack(side="left", padx=5)
        ctk.CTkButton(self.frm_quick_buttons, text="30 мин", command=lambda: self.start_timer(30), **btn_params).pack(side="left", padx=5)
        ctk.CTkButton(self.frm_quick_buttons, text="60 мин", command=lambda: self.start_timer(60), **btn_params).pack(side="left", padx=5)

        # 5. Custom Time Input
        self.frm_custom_time = ctk.CTkFrame(self.tab_timer, fg_color="transparent")
        self.frm_custom_time.grid(row=6, column=0, pady=10)
        
        ctk.CTkEntry(self.frm_custom_time, textvariable=self.custom_time_var, width=60, placeholder_text="Мин").pack(side="left", padx=5)
        ctk.CTkButton(self.frm_custom_time, text="Старт", command=lambda: self.start_custom_timer(), fg_color=THEME_COLOR, hover_color=HOVER_COLOR).pack(side="left", padx=5)

        # 6. Controls (Pause/Stop/Add)
        self.frm_controls = ctk.CTkFrame(self.tab_timer, fg_color="transparent")
        self.frm_controls.grid(row=7, column=0, pady=20)
        
        self.btn_pause = ctk.CTkButton(self.frm_controls, text="Пауза", command=self.pause_timer, state="disabled", fg_color="#FFA500", hover_color="#CD8500")
        self.btn_pause.pack(side="left", padx=5)
        
        self.btn_stop = ctk.CTkButton(self.frm_controls, text="Стоп/Сброс", command=self.stop_timer, state="disabled", fg_color="#DC143C", hover_color="#8B0000")
        self.btn_stop.pack(side="left", padx=5)
        
        self.btn_add = ctk.CTkButton(self.frm_controls, text="+5 мин", command=self.add_time, state="disabled", fg_color=THEME_COLOR, hover_color=HOVER_COLOR)
        self.btn_add.pack(side="left", padx=5)

    def _build_settings_tab(self):
        self.tab_settings.grid_columnconfigure(0, weight=1)
        self.tab_settings.grid_rowconfigure(1, weight=1) # List expands

        # Add new game form
        frm_add = ctk.CTkFrame(self.tab_settings)
        frm_add.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        
        self.entry_name = ctk.CTkEntry(frm_add, placeholder_text="Название игры")
        self.entry_name.pack(side="left", padx=5, expand=True, fill="x")
        
        self.entry_process = ctk.CTkEntry(frm_add, placeholder_text="Имя процесса (например, game.exe)")
        self.entry_process.pack(side="left", padx=5, expand=True, fill="x")
        
        ctk.CTkButton(frm_add, text="Добавить", command=self.add_new_game, fg_color=THEME_COLOR, hover_color=HOVER_COLOR).pack(side="left", padx=5)

        # Games List
        self.scroll_games = ctk.CTkScrollableFrame(self.tab_settings, label_text="Список игр")
        self.scroll_games.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        
        self.refresh_games_list()

    def refresh_games_list(self):
        # Clear existing
        for widget in self.scroll_games.winfo_children():
            widget.destroy()
            
        for game in self.game_manager.games:
            card = ctk.CTkFrame(self.scroll_games, fg_color="transparent", border_width=1, border_color="gray")
            card.pack(fill="x", pady=5)
            
            ctk.CTkLabel(card, text=game["name"], font=(FONT_MAIN, 14, "bold")).pack(side="left", padx=10)
            ctk.CTkLabel(card, text=game["process"], text_color="gray").pack(side="left", padx=10)

    def add_new_game(self):
        name = self.entry_name.get()
        process = self.entry_process.get()
        if name and process:
            self.game_manager.add_game(name, process)
            self.refresh_games_list()
            
            # Update values in dropdown
            self.combo_games.configure(values=self.game_manager.get_game_names())
            
            self.entry_name.delete(0, 'end')
            self.entry_process.delete(0, 'end')

    # --- Timer Control Methods ---

    def start_custom_timer(self):
        try:
            mins = int(self.custom_time_var.get())
            if mins > 0:
                self.start_timer(mins)
        except ValueError:
            pass

    def start_timer(self, minutes: int):
        # Prevent starting if already running
        if self.timer_thread and self.timer_thread.is_alive():
            self.stop_timer()

        game_name = self.selected_game.get()
        if not game_name or game_name == "Нет игр":
            self.lbl_status.configure(text="Ошибка: Не выбрана игра", text_color="#FF5555")
            return

        process_name = self.game_manager.get_game_process(game_name)
        
        self.lbl_status.configure(text=f"Сессия запущена: {game_name}", text_color="#55FF55")
        self.set_controls_state("normal")
        
        # Start Thread
        self.timer_thread = TimerThread(
            duration_minutes=minutes,
            on_tick=self.on_tick,
            on_finish=self.on_finish,
            on_warning=self.on_warning,
            game_process=process_name
        )
        self.timer_thread.start()

    def pause_timer(self):
        if self.timer_thread:
            self.timer_thread.pause()
            new_text = "Продолжить" if self.timer_thread.paused else "Пауза"
            self.btn_pause.configure(text=new_text)
            status_text = "Пауза" if self.timer_thread.paused else "Игра запущена"
            self.lbl_status.configure(text=status_text, text_color="orange" if self.timer_thread.paused else "#55FF55")

    def stop_timer(self):
        if self.timer_thread:
            self.timer_thread.stop()
            self.timer_thread.join(timeout=0.5) # Wait lightly
            self.timer_thread = None
        
        self.lbl_status.configure(text="Сессия остановлена", text_color="white")
        self.lbl_time.configure(text="00:00:00")
        self.progress_bar.set(0)
        self.set_controls_state("disabled")
        self.btn_pause.configure(text="Пауза")

    def add_time(self):
        if self.timer_thread:
            self.timer_thread.add_time(5)

    def set_controls_state(self, state):
        self.btn_pause.configure(state=state)
        self.btn_stop.configure(state=state)
        self.btn_add.configure(state=state)

    # --- Callbacks (Thread-Safe UI Updates) ---
    
    def on_tick(self, remaining: int, total: int):
        # Must schedule update on main thread
        self.after(0, lambda: self._update_ui_tick(remaining, total))

    def _update_ui_tick(self, remaining: int, total: int):
        # Format time
        mins, secs = divmod(remaining, 60)
        hours, mins = divmod(mins, 60)
        time_str = f"{hours:02}:{mins:02}:{secs:02}"
        
        self.lbl_time.configure(text=time_str)
        
        # Progress bar (1.0 is full, 0.0 is empty)
        # We want it to decrease from 1.0 to 0.0
        if total > 0:
            progress = remaining / total
            self.progress_bar.set(progress)

    def on_warning(self):
        self.sound_manager.speak("Уважаемый игрок, до конца сеанса осталось 5 минут")
        # Visual flare optional
        self.after(0, lambda: self.lbl_status.configure(text="ВНИМАНИЕ: 5 МИНУТ", text_color="yellow"))

    def on_finish(self, game_process: str):
        self.after(0, lambda: self._handle_finish(game_process))

    def _handle_finish(self, game_process: str):
        self.lbl_status.configure(text="Сеанс завершен", text_color="#FF5555")
        self.lbl_time.configure(text="00:00:00")
        self.progress_bar.set(0)
        self.set_controls_state("disabled")
        
        # TTS
        self.sound_manager.speak("Время сеанса вышло")
        
        # Kill Process
        if game_process:
            killed = self.process_manager.kill_process(game_process)
            status_msg = f"Процесс {game_process} закрыт." if killed else f"Процесс {game_process} не найден."
            print(status_msg)
            # You might want to show this in status
            self.lbl_status.configure(text=f"Конец: {status_msg}")


if __name__ == "__main__":
    app = VRTimerApp()
    app.mainloop()
