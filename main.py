# =============================================================
#  LEONIFY v4 - Python / Kivy Music Player for Android
#  Main: Python + Kivy | Audio: C via SDL2 | Android: Java
# =============================================================

import os, json, hashlib, time, random, threading, shutil
from pathlib import Path

os.environ["KIVY_NO_ENV_CONFIG"] = "1"
import kivy
kivy.require("2.3.0")

from kivy.config import Config
Config.set("graphics", "resizable", "0")
Config.set("kivy", "keyboard_mode", "systemanddock")

from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen, SlideTransition, NoTransition
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.image import Image
from kivy.uix.popup import Popup
from kivy.uix.slider import Slider
from kivy.uix.widget import Widget
from kivy.core.audio import SoundLoader
from kivy.core.window import Window
from kivy.clock import Clock
from kivy.metrics import dp, sp
from kivy.properties import (StringProperty, NumericProperty,
                              BooleanProperty, ListProperty, ObjectProperty)
from kivy.graphics import Color, Rectangle, RoundedRectangle, Line, Ellipse
from kivy.animation import Animation
from kivy.utils import platform

ANDROID = False
if platform == "android":
    try:
        from android.permissions import request_permissions, Permission
        from android.storage import primary_external_storage_path
        from jnius import autoclass
        AudioManager   = autoclass("android.media.AudioManager")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        ANDROID = True
    except Exception:
        pass

# =============================================================
# DESIGN SYSTEM
# =============================================================
class D:
    BG   = [0.008, 0.016, 0.008, 1]
    BG2  = [0.020, 0.035, 0.020, 1]
    BG3  = [0.031, 0.051, 0.031, 1]
    CARD = [0.047, 0.086, 0.047, 1]
    B1   = [0.067, 0.122, 0.067, 1]
    B2   = [0.102, 0.204, 0.102, 1]
    G    = [0.000, 1.000, 0.533, 1]
    G2   = [0.000, 0.800, 0.400, 1]
    GT   = [0.690, 1.000, 0.720, 1]
    GD   = [0.290, 0.540, 0.353, 1]
    GDD  = [0.165, 0.353, 0.227, 1]
    RED  = [1.000, 0.267, 0.333, 1]
    YEL  = [1.000, 0.800, 0.267, 1]
    R    = dp(8)

# =============================================================
# STORAGE
# =============================================================
def get_data_dir():
    if platform == "android":
        base = primary_external_storage_path()
        d = os.path.join(base, "Leonify")
    else:
        d = os.path.join(str(Path.home()), ".leonify")
    os.makedirs(d, exist_ok=True)
    return d

DATA_DIR   = get_data_dir()
SONGS_DIR  = os.path.join(DATA_DIR, "songs")
COVERS_DIR = os.path.join(DATA_DIR, "covers")
DB_PATH    = os.path.join(DATA_DIR, "db.json")
os.makedirs(SONGS_DIR,  exist_ok=True)
os.makedirs(COVERS_DIR, exist_ok=True)

# =============================================================
# DATABASE
# =============================================================
class DB:
    _data = None

    @classmethod
    def _load(cls):
        if cls._data is None:
            if os.path.exists(DB_PATH):
                try:
                    with open(DB_PATH, "r", encoding="utf-8") as f:
                        cls._data = json.load(f)
                except Exception:
                    cls._data = {}
            else:
                cls._data = {}
        return cls._data

    @classmethod
    def save(cls):
        if cls._data is not None:
            with open(DB_PATH, "w", encoding="utf-8") as f:
                json.dump(cls._data, f, ensure_ascii=False, indent=2)

    @classmethod
    def get(cls, key, default=None):
        return cls._load().get(key, default)

    @classmethod
    def set_val(cls, key, value):
        cls._load()[key] = value
        cls.save()

    @classmethod
    def get_user(cls, uid, suffix, default=None):
        return cls.get(f"u_{uid}_{suffix}", default)

    @classmethod
    def set_user(cls, uid, suffix, value):
        cls.set_val(f"u_{uid}_{suffix}", value)

# =============================================================
# AUTH
# =============================================================
def hash_pw(password, username):
    raw = f"{password}_leonify_{username}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

class Auth:
    current = None

    @classmethod
    def register(cls, username, password):
        u = username.strip().lower()
        if len(u) < 2: return False, "Min. 2 Zeichen!"
        if len(password) < 3: return False, "Passwort min. 3 Zeichen!"
        accs = DB.get("accounts", [])
        if any(a["u"] == u for a in accs): return False, "Username vergeben!"
        uid = f"u{int(time.time())}{random.randint(100,999)}"
        accs.append({"id": uid, "u": u, "h": hash_pw(password, u)})
        DB.set_val("accounts", accs)
        sess = {"id": uid, "username": u}
        DB.set_val("session", sess)
        cls.current = sess
        return True, ""

    @classmethod
    def login(cls, username, password):
        u = username.strip().lower()
        accs = DB.get("accounts", [])
        acc = next((a for a in accs if a["u"] == u), None)
        if not acc or acc["h"] != hash_pw(password, u):
            return False, "Falsche Zugangsdaten!"
        sess = {"id": acc["id"], "username": u}
        DB.set_val("session", sess)
        cls.current = sess
        return True, ""

    @classmethod
    def logout(cls):
        cls.current = None
        DB.set_val("session", None)

    @classmethod
    def restore_session(cls):
        sess = DB.get("session")
        if sess and sess.get("id"):
            cls.current = sess
            return True
        return False

def fmt_time(seconds):
    if not seconds or seconds < 0: return "0:00"
    return f"{int(seconds)//60}:{int(seconds)%60:02d}"

# =============================================================
# PLAYER ENGINE (Python wrapping C/SDL2)
# =============================================================
class Player:
    sound    = None
    queue    = []
    index    = -1
    playing  = False
    shuffle  = False
    repeat   = "none"
    volume   = 1.0
    _progress_cb = None
    _tick_ev     = None

    @classmethod
    def load_and_play(cls, path):
        if cls.sound:
            try: cls.sound.stop(); cls.sound.unload()
            except: pass
            cls.sound = None
        if not path or not os.path.exists(path): return False
        cls.sound = SoundLoader.load(path)
        if not cls.sound: return False
        cls.sound.volume = cls.volume
        cls.sound.bind(on_stop=cls._on_stop)
        cls.sound.play()
        cls.playing = True
        if ANDROID:
            try:
                activity = PythonActivity.mActivity
                am = activity.getSystemService(activity.AUDIO_SERVICE)
                am.requestAudioFocus(None, AudioManager.STREAM_MUSIC,
                                     AudioManager.AUDIOFOCUS_GAIN)
            except: pass
        if cls._tick_ev: cls._tick_ev.cancel()
        cls._tick_ev = Clock.schedule_interval(cls._tick, 0.5)
        return True

    @classmethod
    def _tick(cls, dt):
        if cls.sound and cls.playing and cls._progress_cb:
            cls._progress_cb(cls.sound.get_pos(), cls.sound.length or 1)

    @classmethod
    def _on_stop(cls, *a):
        if cls.playing:
            cls.playing = False
            Clock.schedule_once(lambda dt: cls._auto_next(), 0.2)

    @classmethod
    def _auto_next(cls):
        if cls.repeat == "one": cls.play_index(cls.index)
        elif cls.repeat == "all" or cls.index < len(cls.queue)-1: cls.next()

    @classmethod
    def play_index(cls, idx):
        if 0 <= idx < len(cls.queue):
            cls.index = idx
            cls.load_and_play(cls.queue[idx]["fileUri"])

    @classmethod
    def build_queue(cls, songs, start_id):
        q = list(songs)
        if cls.shuffle: random.shuffle(q)
        cls.queue = q
        idx = next((i for i,s in enumerate(q) if s["id"]==start_id), 0)
        return idx

    @classmethod
    def toggle(cls):
        if not cls.sound: return
        if cls.playing: cls.sound.stop(); cls.playing = False
        else: cls.sound.play(); cls.playing = True

    @classmethod
    def next(cls):
        if not cls.queue: return
        cls.play_index((cls.index+1) % len(cls.queue))

    @classmethod
    def prev(cls):
        if cls.sound and cls.sound.get_pos() > 3: cls.sound.seek(0); return
        if not cls.queue: return
        cls.play_index((cls.index-1) % len(cls.queue))

    @classmethod
    def seek(cls, sec):
        if cls.sound: cls.sound.seek(sec)

    @classmethod
    def set_volume(cls, v):
        cls.volume = v
        if cls.sound: cls.sound.volume = v

    @classmethod
    def stop(cls):
        if cls.sound:
            try: cls.sound.stop(); cls.sound.unload()
            except: pass
            cls.sound = None
        cls.playing = False
        if cls._tick_ev: cls._tick_ev.cancel()

# =============================================================
# UI WIDGETS
# =============================================================
class LeoBtn(Button):
    def __init__(self, txt="", h=dp(44), color=None, bg=None,
                 border_color=None, font_size=None, **kw):
        super().__init__(**kw)
        self.text = txt
        self.size_hint_y = None
        self.height = h
        self.color = color or D.G
        self.font_size = font_size or sp(12)
        self._bg = bg or D.BG3
        self._bc = border_color or D.B2
        self.background_color = [0,0,0,0]
        self.background_normal = ""
        self._draw_bg()
        self.bind(size=self._draw_bg, pos=self._draw_bg)

    def _draw_bg(self, *a):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*self._bc)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[D.R])
            Color(*self._bg)
            RoundedRectangle(
                pos=(self.x+dp(1), self.y+dp(1)),
                size=(self.width-dp(2), self.height-dp(2)),
                radius=[D.R-dp(1)]
            )

class LeoInput(TextInput):
    def __init__(self, hint="", secret=False, **kw):
        super().__init__(**kw)
        self.hint_text = hint
        self.password = secret
        self.size_hint_y = None
        self.height = dp(48)
        self.background_color = D.BG3
        self.foreground_color = D.GT
        self.hint_text_color = D.GDD
        self.cursor_color = D.G
        self.font_size = sp(13)
        self.padding = [dp(14), dp(12)]
        self.multiline = False
        self._draw()
        self.bind(size=self._draw, pos=self._draw)

    def _draw(self, *a):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*D.B2)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[D.R])
            Color(*D.BG3)
            RoundedRectangle(
                pos=(self.x+dp(1), self.y+dp(1)),
                size=(self.width-dp(2), self.height-dp(2)),
                radius=[D.R-dp(1)]
            )

class GreenBar(Widget):
    progress = NumericProperty(0)
    def __init__(self, **kw):
        super().__init__(**kw)
        self.size_hint_y = None
        self.height = dp(3)
        self._draw()
        self.bind(size=self._draw, pos=self._draw, progress=self._draw)

    def _draw(self, *a):
        self.canvas.clear()
        with self.canvas:
            Color(*D.B2)
            Rectangle(pos=self.pos, size=self.size)
            Color(*D.G)
            Rectangle(pos=self.pos, size=(max(0, self.width*self.progress), self.height))

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            pct = (touch.x-self.x)/max(1, self.width)
            self.progress = max(0, min(1, pct))
            if Player.sound and Player.sound.length:
                Player.seek(pct*Player.sound.length)
            return True
        return super().on_touch_down(touch)

class DarkCard(BoxLayout):
    def __init__(self, **kw):
        kw.setdefault("orientation", "horizontal")
        kw.setdefault("padding", dp(10))
        kw.setdefault("spacing", dp(8))
        kw.setdefault("size_hint_y", None)
        kw.setdefault("height", dp(70))
        super().__init__(**kw)
        self._draw()
        self.bind(size=self._draw, pos=self._draw)

    def _draw(self, *a):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*D.CARD)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[D.R])
            Color(*D.B1)
            Line(rounded_rectangle=[self.x,self.y,self.width,self.height,D.R], width=dp(1))

class SongTile(DarkCard):
    def __init__(self, song, on_play=None, on_cover=None, on_add_pl=None,
                 on_rename=None, on_delete=None, on_fav=None,
                 is_playing=False, is_fav=False, **kw):
        super().__init__(**kw)
        self.song = song
        self._on_play = on_play

        # Playing accent
        if is_playing:
            with self.canvas.before:
                Color(*D.G)
                Rectangle(pos=(self.x, self.y), size=(dp(3), self.height))

        # Cover
        cov_box = BoxLayout(size_hint=(None,1), width=dp(50))
        if song.get("coverUri") and os.path.exists(str(song["coverUri"])):
            cov_box.add_widget(Image(source=song["coverUri"],
                                     allow_stretch=True, keep_ratio=True))
        else:
            cov_box.add_widget(Label(text="♪", font_size=sp(22), color=D.GD))
        if on_cover:
            cam = Button(text="📷", size_hint=(None,None), width=dp(18), height=dp(18),
                         background_color=[0]*4, font_size=sp(9), color=D.G2)
            cam.bind(on_press=lambda *a: on_cover(song))
            cov_box.add_widget(cam)
        self.add_widget(cov_box)

        # Info
        info = BoxLayout(orientation="vertical", padding=[0,dp(4)])
        nm = Label(text=song.get("name","?"), color=D.G if is_playing else D.GT,
                   font_size=sp(13), halign="left", valign="middle",
                   shorten=True, shorten_from="right")
        nm.bind(size=lambda *a: setattr(nm, "text_size", nm.size))
        info.add_widget(nm)
        plays = song.get("plays", 0)
        sub_txt = "▶ SPIELT" if is_playing else (f"{plays}× gespielt" if plays>0 else "")
        info.add_widget(Label(text=sub_txt, color=D.GDD, font_size=sp(10),
                               halign="left", valign="middle"))
        self.add_widget(info)

        # Buttons
        btns = BoxLayout(size_hint=(None,1), width=dp(148), spacing=dp(3))
        if is_playing and Player.playing:
            btns.add_widget(Label(text="▶", color=D.G, size_hint=(None,None),
                                   width=dp(20), height=dp(20), font_size=sp(14)))

        def sb(t, col, fn):
            b = Button(text=t, font_size=sp(11), color=col,
                       size_hint=(None,None), width=dp(32), height=dp(32),
                       background_color=[0]*4, background_normal="")
            with b.canvas.before:
                Color(*D.B1)
                RoundedRectangle(pos=b.pos, size=b.size, radius=[dp(5)])
            b.bind(size=lambda *a: b.canvas.before.clear() or
                   self._redraw_small(b))
            b.bind(on_press=fn)
            return b

        if on_fav:
            btns.add_widget(sb("❤" if is_fav else "♡",
                                [1,.4,.53,1] if is_fav else D.GDD,
                                lambda *a: on_fav(song)))
        if on_add_pl:
            btns.add_widget(sb("+PL", D.G2, lambda *a: on_add_pl(song)))
        if on_rename:
            btns.add_widget(sb("✏", D.GD, lambda *a: on_rename(song)))
        if on_delete:
            btns.add_widget(sb("🗑", D.RED, lambda *a: on_delete(song)))
        self.add_widget(btns)
        self.bind(on_touch_down=self._check_play)

    def _redraw_small(self, b):
        with b.canvas.before:
            Color(*D.B1)
            RoundedRectangle(pos=b.pos, size=b.size, radius=[dp(5)])

    def _check_play(self, inst, touch):
        if self.collide_point(*touch.pos):
            if self._on_play: self._on_play(self.song)
            return True

class PlayerBar(BoxLayout):
    def __init__(self, app, **kw):
        super().__init__(orientation="vertical",
                         size_hint_y=None, height=dp(92), **kw)
        self.app = app
        self._draw_bg()
        self.bind(size=self._draw_bg, pos=self._draw_bg)
        self.prog = GreenBar()
        self.add_widget(self.prog)
        row = BoxLayout(size_hint_y=1, padding=[dp(10),dp(4)])
        self.cov_lbl = Label(text="♪", font_size=sp(20), color=D.G,
                              size_hint=(None,1), width=dp(42))
        row.add_widget(self.cov_lbl)
        info = BoxLayout(orientation="vertical", padding=[dp(6),0])
        self.title_lbl = Label(text="–", color=D.GT, font_size=sp(12),
                                halign="left", valign="middle",
                                shorten=True, shorten_from="right")
        self.title_lbl.bind(size=lambda *a: setattr(
            self.title_lbl, "text_size", self.title_lbl.size))
        self.time_lbl = Label(text="0:00 / 0:00", color=D.GDD, font_size=sp(10))
        info.add_widget(self.title_lbl)
        info.add_widget(self.time_lbl)
        row.add_widget(info)
        ctl = BoxLayout(size_hint=(None,1), width=dp(140), spacing=dp(4))
        self.btn_prev = self._cb("⏮")
        self.btn_prev.bind(on_press=lambda *a: Player.prev())
        self.btn_play = self._cb("▶", big=True)
        self.btn_play.bind(on_press=lambda *a: self._toggle())
        self.btn_next = self._cb("⏭")
        self.btn_next.bind(on_press=lambda *a: Player.next())
        ctl.add_widget(self.btn_prev)
        ctl.add_widget(self.btn_play)
        ctl.add_widget(self.btn_next)
        row.add_widget(ctl)
        self.add_widget(row)
        vol = BoxLayout(size_hint_y=None, height=dp(26),
                        padding=[dp(10),dp(2)])
        vol.add_widget(Label(text="🔈", size_hint=(None,1), width=dp(20),
                              font_size=sp(11), color=D.GDD))
        vs = Slider(min=0, max=1, value=1)
        vs.bind(value=lambda i,v: Player.set_volume(v))
        vol.add_widget(vs)
        vol.add_widget(Label(text="🔊", size_hint=(None,1), width=dp(20),
                              font_size=sp(11), color=D.GDD))
        self.add_widget(vol)
        Player._progress_cb = self._on_prog

    def _cb(self, txt, big=False):
        b = Button(text=txt, font_size=sp(16 if big else 13),
                   color=D.G if big else D.GD,
                   size_hint=(None,None),
                   width=dp(42 if big else 32), height=dp(42 if big else 32),
                   background_color=[0]*4, background_normal="")
        with b.canvas.before:
            Color(*(D.B2 if big else D.B1))
            RoundedRectangle(pos=b.pos, size=b.size, radius=[dp(6)])
        return b

    def _toggle(self):
        Player.toggle()
        self.btn_play.text = "⏸" if Player.playing else "▶"

    def _on_prog(self, pos, dur):
        self.prog.progress = pos / max(dur, 1)
        self.time_lbl.text = f"{fmt_time(pos)} / {fmt_time(dur)}"

    def _draw_bg(self, *a):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*D.BG2)
            Rectangle(pos=self.pos, size=self.size)
            Color(*D.B2)
            Line(points=[self.x, self.top, self.right, self.top], width=dp(1))

    def update_song(self, song):
        self.title_lbl.text = song.get("name","–") if song else "–"
        self.btn_play.text = "⏸" if Player.playing else "▶"

# =============================================================
# SCREENS
# =============================================================
class BaseScreen(Screen):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.app = app
        with self.canvas.before:
            Color(*D.BG)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(
            size=lambda *a: setattr(self._bg, "size", self.size),
            pos=lambda *a:  setattr(self._bg, "pos",  self.pos)
        )

# ── LOGIN ──────────────────────────────────────────────────────────
class LoginScreen(BaseScreen):
    def __init__(self, app, **kw):
        super().__init__(app, name="login", **kw)
        self.mode = "in"
        self._build()

    def _build(self):
        root = FloatLayout()
        box = BoxLayout(orientation="vertical", spacing=dp(10),
                        size_hint=(0.88, None),
                        pos_hint={"center_x":0.5,"center_y":0.5})
        logo = Label(text="Leonify", font_size=sp(44), bold=True,
                     color=D.G, size_hint_y=None, height=dp(68))
        sub  = Label(text="// DEINE MUSIK. DEIN ACCOUNT.",
                     font_size=sp(9), color=D.GDD, size_hint_y=None, height=dp(22))
        box.add_widget(logo)
        box.add_widget(sub)
        box.add_widget(Widget(size_hint_y=None, height=dp(16)))
        tabs = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(4))
        self.btn_in  = LeoBtn("EINLOGGEN",    bg=D.BG3, border_color=D.B2)
        self.btn_reg = LeoBtn("REGISTRIEREN", bg=D.BG3, border_color=D.B2)
        self.btn_in.bind( on_press=lambda *a: self._mode("in"))
        self.btn_reg.bind(on_press=lambda *a: self._mode("reg"))
        tabs.add_widget(self.btn_in)
        tabs.add_widget(self.btn_reg)
        box.add_widget(tabs)
        self.err = Label(text="", color=D.RED, font_size=sp(11),
                         size_hint_y=None, height=dp(22))
        box.add_widget(self.err)
        lbl_u = Label(text="BENUTZERNAME", color=D.GDD, font_size=sp(10),
                      size_hint_y=None, height=dp(18), halign="left", valign="middle")
        lbl_u.bind(size=lambda *a: setattr(lbl_u,"text_size",lbl_u.size))
        self.u_inp = LeoInput(hint="dein name")
        lbl_p = Label(text="PASSWORT", color=D.GDD, font_size=sp(10),
                      size_hint_y=None, height=dp(18), halign="left", valign="middle")
        lbl_p.bind(size=lambda *a: setattr(lbl_p,"text_size",lbl_p.size))
        self.p_inp = LeoInput(hint="••••••••", secret=True)
        box.add_widget(lbl_u)
        box.add_widget(self.u_inp)
        box.add_widget(lbl_p)
        box.add_widget(self.p_inp)
        box.add_widget(Widget(size_hint_y=None, height=dp(8)))
        self.sub_btn = LeoBtn("EINLOGGEN", color=D.G, h=dp(50))
        self.sub_btn.bind(on_press=self._auth)
        box.add_widget(self.sub_btn)
        box.height = sum(
            (c.height if hasattr(c,"height") else dp(40))
            for c in box.children
        ) + box.spacing * len(box.children) + dp(20)
        root.add_widget(box)
        self.add_widget(root)
        self._mode("in")

    def _mode(self, m):
        self.mode = m
        self.err.text = ""
        self.btn_in.color  = D.G   if m=="in"  else D.GDD
        self.btn_reg.color = D.GDD if m=="in"  else D.G
        self.sub_btn.text = "EINLOGGEN" if m=="in" else "REGISTRIEREN"

    def _auth(self, *a):
        u, p = self.u_inp.text.strip(), self.p_inp.text
        ok, err = (Auth.login if self.mode=="in" else Auth.register)(u, p)
        if ok: self.app.go_main()
        else:  self.err.text = err

# ── LIBRARY ────────────────────────────────────────────────────────
class LibraryScreen(BaseScreen):
    def __init__(self, app, **kw):
        super().__init__(app, name="library", **kw)
        self.srch_q = ""
        self._build()

    def _build(self):
        root = BoxLayout(orientation="vertical")
        srch = BoxLayout(size_hint_y=None, height=dp(50),
                         padding=[dp(10),dp(6)])
        self.srch = LeoInput(hint="🔍  Song suchen...")
        self.srch.bind(text=lambda i,t: setattr(self,"srch_q",t.lower()) or self.refresh())
        srch.add_widget(self.srch)
        root.add_widget(srch)
        add = LeoBtn("+ MUSIK HINZUFÜGEN  ·  MP3 / WAV / M4A",
                     h=dp(46), color=D.GD, border_color=D.B2)
        add.bind(on_press=self._import)
        root.add_widget(add)
        root.add_widget(Label(text="// BIBLIOTHEK", color=D.GDD,
                              font_size=sp(10), size_hint_y=None, height=dp(26)))
        sv = ScrollView(do_scroll_x=False)
        self.lb = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6))
        self.lb.bind(minimum_height=self.lb.setter("height"))
        sv.add_widget(self.lb)
        root.add_widget(sv)
        self.add_widget(root)

    def _import(self, *a):
        if ANDROID:
            from android.storage import primary_external_storage_path
            music = os.path.join(primary_external_storage_path(), "Music")
            exts = {".mp3",".wav",".m4a",".ogg",".flac"}
            for r,ds,fs in os.walk(music):
                for fn in fs:
                    if Path(fn).suffix.lower() in exts:
                        self.app.add_song(os.path.join(r,fn))
            self.refresh()
        else:
            from kivy.uix.filechooser import FileChooserListView
            c = BoxLayout(orientation="vertical")
            fc = FileChooserListView(filters=["*.mp3","*.wav","*.m4a","*.ogg","*.flac"],
                                     multiselect=True)
            c.add_widget(fc)
            btns = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
            def go(*a):
                for p in fc.selection: self.app.add_song(p)
                pop.dismiss(); self.refresh()
            ok = LeoBtn("HINZUFÜGEN", color=D.G)
            ok.bind(on_press=go)
            ca = LeoBtn("ABBRUCH", color=D.GD)
            btns.add_widget(ca); btns.add_widget(ok)
            c.add_widget(btns)
            pop = Popup(title="Musik auswählen", content=c,
                        size_hint=(0.95,0.9), background_color=D.BG2)
            ca.bind(on_press=pop.dismiss)
            pop.open()

    def refresh(self):
        self.lb.clear_widgets()
        uid = Auth.current["id"] if Auth.current else None
        if not uid: return
        songs = DB.get_user(uid, "songs", [])
        favs  = set(DB.get_user(uid, "favs", []))
        if self.srch_q:
            songs = [s for s in songs if self.srch_q in s.get("name","").lower()]
        cur_id = (Player.queue[Player.index]["id"]
                  if 0 <= Player.index < len(Player.queue) else None)
        if not songs:
            self.lb.add_widget(Label(
                text="KEINE SONGS\nTippe auf + MUSIK HINZUFÜGEN",
                color=D.GDD, font_size=sp(12), halign="center",
                size_hint_y=None, height=dp(100)))
            return
        for s in songs:
            self.lb.add_widget(SongTile(
                song=s, is_playing=(s["id"]==cur_id), is_fav=(s["id"] in favs),
                on_play=self.app.play_song,
                on_cover=self.app.pick_cover,
                on_add_pl=self.app.open_add_to_pl,
                on_rename=lambda s: self.app.open_rename("song",s),
                on_delete=lambda s: self.app.delete_song(s, self.refresh),
                on_fav=lambda s: self.app.toggle_fav(s["id"], self.refresh),
            ))

# ── PLAYLISTS ──────────────────────────────────────────────────────
class PlaylistsScreen(BaseScreen):
    def __init__(self, app, **kw):
        super().__init__(app, name="playlists", **kw)
        self._build()

    def _build(self):
        root = BoxLayout(orientation="vertical")
        add = LeoBtn("+ NEUE PLAYLIST ERSTELLEN", h=dp(46), color=D.GD, border_color=D.B2)
        add.bind(on_press=self._new)
        root.add_widget(add)
        root.add_widget(Label(text="// PLAYLISTS", color=D.GDD,
                              font_size=sp(10), size_hint_y=None, height=dp(26)))
        sv = ScrollView(do_scroll_x=False)
        self.grid = GridLayout(cols=2, size_hint_y=None, spacing=dp(8), padding=dp(8))
        self.grid.bind(minimum_height=self.grid.setter("height"))
        sv.add_widget(self.grid)
        root.add_widget(sv)
        self.add_widget(root)

    def _new(self, *a):
        c = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(10))
        inp = LeoInput(hint="Playlist Name")
        c.add_widget(inp)
        btns = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        def create(*a):
            n = inp.text.strip()
            if not n: return
            uid = Auth.current["id"]
            pls = DB.get_user(uid,"playlists",[])
            pls.append({"id":f"P{int(time.time())}","name":n,"songs":[]})
            DB.set_user(uid,"playlists",pls)
            pop.dismiss(); self.refresh()
        ok = LeoBtn("ERSTELLEN", color=D.G)
        ok.bind(on_press=create)
        ca = LeoBtn("ABBRUCH", color=D.GD)
        btns.add_widget(ca); btns.add_widget(ok)
        c.add_widget(btns)
        pop = Popup(title="Neue Playlist", content=c,
                    size_hint=(0.88,None), height=dp(200), background_color=D.BG2)
        ca.bind(on_press=pop.dismiss)
        pop.open()

    def refresh(self):
        self.grid.clear_widgets()
        uid = Auth.current["id"] if Auth.current else None
        if not uid: return
        pls = DB.get_user(uid,"playlists",[])
        if not pls:
            self.grid.add_widget(Label(text="KEINE PLAYLISTS",
                                       color=D.GDD, font_size=sp(12),
                                       size_hint_y=None, height=dp(80)))
            return
        for pl in pls:
            btn = Button(
                text=f"[b]{pl['name']}[/b]\n[size=10sp]{len(pl['songs'])} SONGS[/size]",
                markup=True, font_size=sp(12), color=D.GT,
                size_hint_y=None, height=dp(100),
                background_color=[0]*4, background_normal="")
            self._draw_card(btn)
            btn.bind(size=lambda *a,b=btn: self._draw_card(b))
            btn.bind(on_press=lambda *a, p=pl: self.app.open_pl_detail(p))
            self.grid.add_widget(btn)

    def _draw_card(self, b):
        b.canvas.before.clear()
        with b.canvas.before:
            Color(*D.CARD)
            RoundedRectangle(pos=b.pos, size=b.size, radius=[D.R])
            Color(*D.B1)
            Line(rounded_rectangle=[b.x,b.y,b.width,b.height,D.R], width=dp(1))

# ── FAVORITES ──────────────────────────────────────────────────────
class FavsScreen(BaseScreen):
    def __init__(self, app, **kw):
        super().__init__(app, name="favs", **kw)
        self._build()

    def _build(self):
        root = BoxLayout(orientation="vertical")
        root.add_widget(Label(text="// FAVORITEN", color=D.GDD,
                              font_size=sp(10), size_hint_y=None, height=dp(26)))
        sv = ScrollView(do_scroll_x=False)
        self.lb = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6))
        self.lb.bind(minimum_height=self.lb.setter("height"))
        sv.add_widget(self.lb)
        root.add_widget(sv)
        self.add_widget(root)

    def refresh(self):
        self.lb.clear_widgets()
        uid = Auth.current["id"] if Auth.current else None
        if not uid: return
        all_s = DB.get_user(uid,"songs",[])
        favs  = set(DB.get_user(uid,"favs",[]))
        fs    = [s for s in all_s if s["id"] in favs]
        if not fs:
            self.lb.add_widget(Label(
                text="KEINE FAVORITEN\nTippe auf ❤ bei einem Song!",
                color=D.GDD, font_size=sp(12), halign="center",
                size_hint_y=None, height=dp(100)))
            return
        cur_id = (Player.queue[Player.index]["id"]
                  if 0 <= Player.index < len(Player.queue) else None)
        for s in fs:
            self.lb.add_widget(SongTile(
                song=s, is_playing=(s["id"]==cur_id), is_fav=True,
                on_play=self.app.play_song,
                on_cover=self.app.pick_cover,
                on_add_pl=self.app.open_add_to_pl,
                on_rename=lambda s: self.app.open_rename("song",s),
                on_delete=lambda s: self.app.delete_song(s, self.refresh),
                on_fav=lambda s: self.app.toggle_fav(s["id"], self.refresh),
            ))

# ── PLAYLIST DETAIL ─────────────────────────────────────────────────
class PLDetailScreen(BaseScreen):
    def __init__(self, app, **kw):
        super().__init__(app, name="pl_detail", **kw)
        self.pl = None
        self._build()

    def _build(self):
        root = BoxLayout(orientation="vertical")
        hdr = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(8), padding=[dp(8),dp(6)])
        back = LeoBtn("‹ ZURÜCK", color=D.GD, border_color=D.B1, h=dp(40))
        back.bind(on_press=lambda *a: self.app.go_back())
        hdr.add_widget(back)
        self.nm = Label(text="", color=D.G, font_size=sp(15), bold=True)
        hdr.add_widget(self.nm)
        root.add_widget(hdr)
        acts = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6), padding=[dp(8),dp(2)])
        pb = LeoBtn("▶ PLAY", color=D.G, h=dp(42))
        pb.bind(on_press=lambda *a: self._play_all())
        rb = LeoBtn("✏", color=D.GD, h=dp(42))
        rb.bind(on_press=lambda *a: self.app.open_rename("pl", self.pl))
        db = LeoBtn("✖", color=D.RED, border_color=D.RED, h=dp(42))
        db.bind(on_press=lambda *a: self._delete())
        acts.add_widget(pb); acts.add_widget(rb); acts.add_widget(db)
        root.add_widget(acts)
        root.add_widget(Label(text="// SONGS IN PLAYLIST", color=D.GDD,
                              font_size=sp(10), size_hint_y=None, height=dp(24)))
        sv = ScrollView(do_scroll_x=False)
        self.lb = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6))
        self.lb.bind(minimum_height=self.lb.setter("height"))
        sv.add_widget(self.lb)
        root.add_widget(sv)
        self.add_widget(root)

    def load(self, pl):
        self.pl = pl
        self.refresh()

    def refresh(self):
        if not self.pl: return
        self.nm.text = self.pl["name"]
        self.lb.clear_widgets()
        uid = Auth.current["id"]
        all_s = DB.get_user(uid,"songs",[])
        favs  = set(DB.get_user(uid,"favs",[]))
        pl_s  = [s for s in all_s if s["id"] in self.pl["songs"]]
        cur_id= (Player.queue[Player.index]["id"]
                 if 0 <= Player.index < len(Player.queue) else None)
        if not pl_s:
            self.lb.add_widget(Label(
                text="LEER\nGehe zu MUSIK → +PL",
                color=D.GDD, font_size=sp(12), halign="center",
                size_hint_y=None, height=dp(80)))
            return
        for s in pl_s:
            self.lb.add_widget(SongTile(
                song=s, is_playing=(s["id"]==cur_id), is_fav=(s["id"] in favs),
                on_play=lambda s: self.app.play_song(s, from_pl=self.pl),
                on_cover=self.app.pick_cover,
                on_add_pl=self.app.open_add_to_pl,
                on_rename=lambda s: self.app.open_rename("song",s),
                on_delete=lambda s: self.app.remove_from_pl(self.pl, s["id"], self.refresh),
                on_fav=lambda s: self.app.toggle_fav(s["id"], self.refresh),
            ))

    def _play_all(self):
        if not self.pl or not self.pl["songs"]: return
        uid  = Auth.current["id"]
        all_s= DB.get_user(uid,"songs",[])
        pl_s = [s for s in all_s if s["id"] in self.pl["songs"]]
        if pl_s: self.app.play_song(pl_s[0], from_pl=self.pl)

    def _delete(self):
        if not self.pl: return
        uid = Auth.current["id"]
        pls = DB.get_user(uid,"playlists",[])
        DB.set_user(uid,"playlists",[p for p in pls if p["id"]!=self.pl["id"]])
        self.pl = None
        self.app.go_back()
        self.app.refresh_all()

# ── MAIN (shell with tabs + player bar) ────────────────────────────
class MainScreen(BaseScreen):
    def __init__(self, app, **kw):
        super().__init__(app, name="main", **kw)
        self._build()

    def _build(self):
        root = BoxLayout(orientation="vertical")
        # Header
        hdr = BoxLayout(size_hint_y=None, height=dp(50), padding=[dp(12),dp(6)])
        with hdr.canvas.before:
            Color(*D.BG2)
            Rectangle(pos=hdr.pos, size=hdr.size)
        hdr.bind(pos=lambda *a: hdr.canvas.before.clear() or self._draw_hdr(hdr),
                 size=lambda *a: hdr.canvas.before.clear() or self._draw_hdr(hdr))
        logo = Label(text="Leonify", font_size=sp(19), bold=True,
                     color=D.G, size_hint=(None,1), width=dp(120))
        hdr.add_widget(logo)
        self.u_lbl = Label(text="", font_size=sp(10), color=D.GDD)
        hdr.add_widget(self.u_lbl)
        out = LeoBtn("LOGOUT", color=D.GDD, border_color=D.B2,
                     h=dp(32), font_size=sp(10))
        out.size_hint = (None,None); out.width=dp(72)
        out.bind(on_press=self._logout)
        hdr.add_widget(out)
        root.add_widget(hdr)
        # Inner SM
        self.ism = ScreenManager(transition=NoTransition())
        self.lib = LibraryScreen(self.app, name="t_lib")
        self.pls = PlaylistsScreen(self.app, name="t_pls")
        self.fav = FavsScreen(self.app, name="t_fav")
        self.ism.add_widget(self.lib)
        self.ism.add_widget(self.pls)
        self.ism.add_widget(self.fav)
        root.add_widget(self.ism)
        # Player bar
        self.pbar = PlayerBar(self.app, size_hint_y=None, height=dp(92))
        root.add_widget(self.pbar)
        # Tab bar
        tabs = BoxLayout(size_hint_y=None, height=dp(52))
        with tabs.canvas.before:
            Color(*D.BG2); Rectangle(pos=tabs.pos, size=tabs.size)
        tabs.bind(pos=lambda *a: tabs.canvas.before.clear(),
                  size=lambda *a: tabs.canvas.before.clear())
        self._tab_btns = []
        for lbl, sn in [("♪ MUSIK","t_lib"),("≡ LISTEN","t_pls"),("❤ FAV","t_fav")]:
            b = Button(text=lbl, font_size=sp(11), color=D.GDD,
                       background_color=[0]*4, background_normal="")
            b._sn = sn
            b.bind(on_press=self._switch)
            tabs.add_widget(b)
            self._tab_btns.append(b)
        root.add_widget(tabs)
        self.add_widget(root)
        self._active(self._tab_btns[0])

    def _draw_hdr(self, hdr):
        with hdr.canvas.before:
            Color(*D.BG2); Rectangle(pos=hdr.pos, size=hdr.size)

    def _switch(self, btn):
        self.ism.current = btn._sn
        self._active(btn)
        self._refresh_tab()

    def _active(self, active):
        for b in self._tab_btns:
            b.color = D.G if b is active else D.GDD

    def _logout(self, *a):
        Auth.logout(); Player.stop()
        self.app.sm.current = "login"

    def on_enter(self):
        if Auth.current:
            self.u_lbl.text = f"// {Auth.current['username'].upper()}"
        self._refresh_tab()

    def _refresh_tab(self):
        t = self.ism.current
        if t=="t_lib":  self.lib.refresh()
        elif t=="t_pls": self.pls.refresh()
        elif t=="t_fav": self.fav.refresh()

    def refresh_all(self):
        self.lib.refresh(); self.pls.refresh(); self.fav.refresh()

# =============================================================
# APPLICATION
# =============================================================
class LeonifyApp(App):
    title = "Leonify"

    def build(self):
        Window.clearcolor = D.BG
        if ANDROID:
            request_permissions([
                Permission.READ_EXTERNAL_STORAGE,
                Permission.WRITE_EXTERNAL_STORAGE,
                Permission.READ_MEDIA_AUDIO,
            ])
        self.sm = ScreenManager(transition=SlideTransition())
        self.login_scr  = LoginScreen(self)
        self.main_scr   = MainScreen(self)
        self.pl_det_scr = PLDetailScreen(self)
        for s in [self.login_scr, self.main_scr, self.pl_det_scr]:
            self.sm.add_widget(s)
        self.sm.current = "main" if Auth.restore_session() else "login"
        Clock.schedule_interval(self._tick, 1.0)
        return self.sm

    def _tick(self, dt):
        if self.sm.current == "main":
            cur = (Player.queue[Player.index]
                   if 0 <= Player.index < len(Player.queue) else None)
            self.main_scr.pbar.update_song(cur)

    def go_main(self):
        self.sm.transition = SlideTransition(direction="left")
        self.sm.current = "main"

    def go_back(self):
        self.sm.transition = SlideTransition(direction="right")
        self.sm.current = "main"

    def open_pl_detail(self, pl):
        self.pl_det_scr.load(pl)
        self.sm.transition = SlideTransition(direction="left")
        self.sm.current = "pl_detail"

    def refresh_all(self):
        self.main_scr.refresh_all()

    def add_song(self, path):
        uid = Auth.current["id"] if Auth.current else None
        if not uid: return
        songs = DB.get_user(uid,"songs",[])
        if any(s.get("origPath")==path for s in songs): return
        sid  = f"S{int(time.time())}{random.randint(100,999)}"
        name = Path(path).stem.replace("_"," ").replace("-"," ").strip()
        ext  = Path(path).suffix
        dest = os.path.join(SONGS_DIR, sid+ext)
        try: shutil.copy2(path, dest)
        except: dest = path
        songs.append({"id":sid,"name":name,"fileUri":dest,
                      "origPath":path,"coverUri":None,"plays":0})
        DB.set_user(uid,"songs",songs)

    def play_song(self, song, from_pl=None):
        uid = Auth.current["id"] if Auth.current else None
        if not uid: return
        songs = DB.get_user(uid,"songs",[])
        src   = ([s for s in songs if s["id"] in from_pl["songs"]]
                 if from_pl else songs)
        idx   = Player.build_queue(src, song["id"])
        Player.index = idx
        Player.load_and_play(song["fileUri"])
        all_s = DB.get_user(uid,"songs",[])
        for s in all_s:
            if s["id"]==song["id"]: s["plays"]=s.get("plays",0)+1
        DB.set_user(uid,"songs",all_s)
        self.refresh_all()

    def delete_song(self, song, cb=None):
        uid = Auth.current["id"] if Auth.current else None
        if not uid: return
        def go(*a):
            pop.dismiss()
            songs = DB.get_user(uid,"songs",[])
            DB.set_user(uid,"songs",[s for s in songs if s["id"]!=song["id"]])
            pls = DB.get_user(uid,"playlists",[])
            for p in pls: p["songs"]=[i for i in p["songs"] if i!=song["id"]]
            DB.set_user(uid,"playlists",pls)
            favs = DB.get_user(uid,"favs",[])
            DB.set_user(uid,"favs",[f for f in favs if f!=song["id"]])
            try:
                if song.get("fileUri") and os.path.exists(song["fileUri"]):
                    os.remove(song["fileUri"])
            except: pass
            if (0 <= Player.index < len(Player.queue) and
                    Player.queue[Player.index]["id"]==song["id"]):
                Player.stop()
            self.refresh_all()
            if cb: cb()
        c = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        c.add_widget(Label(text=f'"{song["name"]}" löschen?',
                           color=D.GT, font_size=sp(13)))
        btns = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        ca = LeoBtn("ABBRUCH", color=D.GD)
        ok = LeoBtn("LÖSCHEN",  color=D.RED, border_color=D.RED)
        btns.add_widget(ca); btns.add_widget(ok)
        c.add_widget(btns)
        pop = Popup(title="Song löschen", content=c,
                    size_hint=(0.85,None), height=dp(180), background_color=D.BG2)
        ca.bind(on_press=pop.dismiss)
        ok.bind(on_press=go)
        pop.open()

    def toggle_fav(self, song_id, cb=None):
        uid = Auth.current["id"] if Auth.current else None
        if not uid: return
        favs = DB.get_user(uid,"favs",[])
        if song_id in favs: favs.remove(song_id)
        else: favs.append(song_id)
        DB.set_user(uid,"favs",favs)
        self.refresh_all()
        if cb: cb()

    def pick_cover(self, song):
        from kivy.uix.filechooser import FileChooserListView
        c = BoxLayout(orientation="vertical")
        fc = FileChooserListView(filters=["*.jpg","*.jpeg","*.png","*.webp"])
        c.add_widget(fc)
        btns = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        def save(*a):
            if not fc.selection: return
            uid  = Auth.current["id"]
            src  = fc.selection[0]
            dest = os.path.join(COVERS_DIR, song["id"]+Path(src).suffix)
            try:
                shutil.copy2(src, dest)
                songs = DB.get_user(uid,"songs",[])
                for s in songs:
                    if s["id"]==song["id"]: s["coverUri"]=dest
                DB.set_user(uid,"songs",songs)
                self.refresh_all()
            except Exception as e: print("Cover err:", e)
            pop.dismiss()
        ok = LeoBtn("SPEICHERN", color=D.G)
        ok.bind(on_press=save)
        ca = LeoBtn("ABBRUCH",   color=D.GD)
        btns.add_widget(ca); btns.add_widget(ok)
        c.add_widget(btns)
        pop = Popup(title="Cover auswählen", content=c,
                    size_hint=(0.95,0.9), background_color=D.BG2)
        ca.bind(on_press=pop.dismiss)
        pop.open()

    def open_add_to_pl(self, song):
        uid = Auth.current["id"] if Auth.current else None
        if not uid: return
        pls = DB.get_user(uid,"playlists",[])
        c = BoxLayout(orientation="vertical", spacing=dp(6), padding=dp(10))
        if not pls:
            c.add_widget(Label(text="Keine Playlists!\nErstelle zuerst eine.",
                               color=D.GDD, font_size=sp(12)))
        else:
            sv = ScrollView(size_hint_y=1)
            box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6))
            box.bind(minimum_height=box.setter("height"))
            for pl in pls:
                in_pl = song["id"] in pl["songs"]
                btn   = LeoBtn(f"{'✅' if in_pl else '➕'}  {pl['name']}",
                               color=D.GT, h=dp(46))
                def make_cb(p, already):
                    def cb(*a):
                        if already: p["songs"]=[i for i in p["songs"] if i!=song["id"]]
                        else:
                            if song["id"] not in p["songs"]: p["songs"].append(song["id"])
                        DB.set_user(uid,"playlists",pls)
                        pop.dismiss(); self.refresh_all()
                    return cb
                btn.bind(on_press=make_cb(pl, in_pl))
                box.add_widget(btn)
            sv.add_widget(box); c.add_widget(sv)
        ca = LeoBtn("SCHLIESSEN", color=D.GD)
        c.add_widget(ca)
        pop = Popup(title="Zu Playlist hinzufügen", content=c,
                    size_hint=(0.88,0.7), background_color=D.BG2)
        ca.bind(on_press=pop.dismiss)
        pop.open()

    def open_rename(self, kind, obj):
        uid = Auth.current["id"] if Auth.current else None
        if not uid: return
        c = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(10))
        inp = LeoInput(hint="Neuer Name")
        inp.text = obj.get("name","")
        c.add_widget(inp)
        btns = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        def save(*a):
            v = inp.text.strip()
            if not v: return
            if kind=="song":
                songs = DB.get_user(uid,"songs",[])
                for s in songs:
                    if s["id"]==obj["id"]: s["name"]=v
                DB.set_user(uid,"songs",songs)
            else:
                pls = DB.get_user(uid,"playlists",[])
                for p in pls:
                    if p["id"]==obj["id"]: p["name"]=v
                DB.set_user(uid,"playlists",pls)
                if (self.pl_det_scr.pl and
                        self.pl_det_scr.pl["id"]==obj["id"]):
                    self.pl_det_scr.pl["name"]=v
                    self.pl_det_scr.refresh()
            pop.dismiss(); self.refresh_all()
        ok = LeoBtn("SPEICHERN", color=D.G)
        ok.bind(on_press=save)
        ca = LeoBtn("ABBRUCH",   color=D.GD)
        btns.add_widget(ca); btns.add_widget(ok)
        c.add_widget(btns)
        pop = Popup(title="Umbenennen", content=c,
                    size_hint=(0.88,None), height=dp(200), background_color=D.BG2)
        ca.bind(on_press=pop.dismiss)
        pop.open()

    def remove_from_pl(self, pl, song_id, cb=None):
        uid = Auth.current["id"] if Auth.current else None
        if not uid: return
        pl["songs"] = [i for i in pl["songs"] if i!=song_id]
        pls = DB.get_user(uid,"playlists",[])
        for p in pls:
            if p["id"]==pl["id"]: p["songs"]=pl["songs"]
        DB.set_user(uid,"playlists",pls)
        self.refresh_all()
        if cb: cb()

if __name__ == "__main__":
    LeonifyApp().run()
