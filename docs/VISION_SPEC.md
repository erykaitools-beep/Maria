# M.A.R.I.A. - Specyfikacja Percepcji Wizualnej (Oko)

> **Data utworzenia:** 2026-02-01
> **Status:** Architektura do opracowania
> **Filozofia:** Oko jako organ, nie urzadzenie - graceful degradation zamiast 0/1
> **Podejscie:** Wolniej, ale dokladniej. Kazda faza w pelni przetestowana.

---

## 1. Zasada nadrzedna: Biologiczna inspiracja

### Ludzkie oko vs. kamera cyfrowa

| Aspekt | Kamera cyfrowa | Ludzkie oko | M.A.R.I.A. Vision |
|--------|----------------|-------------|-------------------|
| Awaria | 0 lub 1 (dziala/nie dziala) | Graceful degradation | Graceful degradation |
| Adaptacja | Brak / manualna | Automatyczna (zrenica) | Multi-mode adaptation |
| Przetwarzanie | Surowy obraz | Wstepne w siatkówce | Edge preprocessing |
| Uwaga | Caly kadr rowny | Fovea (centrum ostre) | Attention mechanism |
| Bol | Brak | Sygnalizuje problem | Health alerts |

### Graceful Degradation - kluczowa zasada

```
FULL VISION (100%)
    |
    v uszkodzenie koloru
GRAYSCALE VISION (80%)
    |
    v uszkodzenie rozdzielczosci
LOW-RES VISION (60%)
    |
    v uszkodzenie ostrosci
BLUR DETECTION (40%)
    |
    v uszkodzenie streamu
FRAME-BY-FRAME (20%)
    |
    v uszkodzenie sensora
LIGHT/DARK ONLY (5%)
    |
    v calkowita awaria
BLIND MODE (0%) - tylko inne zmysly
```

Maria NIGDY nie mowi "kamera nie dziala" - mowi "widze bardzo slabo" lub "widze tylko swiatlo".

---

## 2. Architektura warstwowa

```
┌─────────────────────────────────────────────────────────────┐
│                    MARIA CONSCIOUSNESS                       │
│              (Unified Perception - jedno "ja")               │
├─────────────────────────────────────────────────────────────┤
│                    VISION CORTEX                             │
│     Integracja wszystkich kanalow wizualnych                 │
│     Attention mechanism, memory binding                      │
├──────────────┬──────────────┬──────────────┬────────────────┤
│   FACE       │   SCENE      │    OCR       │    MOTION      │
│   MODULE     │   MODULE     │   MODULE     │    MODULE      │
│              │              │              │                │
│  Twarze,     │  Obiekty,    │  Tekst,      │  Ruch,         │
│  emocje,     │  przestrzen, │  dokumenty,  │  gesty,        │
│  identyfikacja│ kontekst    │  ekrany      │  niebezpieczenstwo│
├──────────────┴──────────────┴──────────────┴────────────────┤
│                    PREPROCESSING LAYER                       │
│     Normalizacja, denoising, color correction                │
│     Quality assessment, degradation detection                │
├─────────────────────────────────────────────────────────────┤
│                    SENSOR ABSTRACTION                        │
│     Unified interface for all camera types                   │
├──────────┬──────────┬──────────┬──────────┬─────────────────┤
│  USB     │  IP/RTSP │  RPi     │  Thermal │  Future         │
│  Webcam  │  Camera  │  Camera  │  IR      │  sensors...     │
└──────────┴──────────┴──────────┴──────────┴─────────────────┘
```

---

## 3. Sensor Abstraction Layer

### Interfejs bazowy (protocol)

```python
class VisionSensor(Protocol):
    """
    Abstrakcyjny interfejs dla wszystkich sensorow wizualnych.
    Kazdy sensor musi implementowac te metody.
    """

    @property
    def sensor_id(self) -> str:
        """Unikalny identyfikator sensora."""
        ...

    @property
    def capabilities(self) -> SensorCapabilities:
        """Co sensor potrafi (rozdzielczosc, FPS, tryby)."""
        ...

    @property
    def health(self) -> SensorHealth:
        """Stan zdrowia sensora (0.0-1.0 + szczegoly)."""
        ...

    def capture_frame(self) -> Optional[Frame]:
        """
        Pobierz pojedyncza klatke.
        Zwraca None jesli sensor calkowicie niesprawny.
        """
        ...

    def get_stream(self) -> Iterator[Frame]:
        """Generator klatek (dla ciaglego streamu)."""
        ...

    def set_mode(self, mode: VisionMode) -> bool:
        """Zmien tryb (dzien/noc/IR/etc)."""
        ...

    def diagnose(self) -> DiagnosticReport:
        """Pelna diagnostyka sensora."""
        ...
```

### SensorCapabilities

```python
@dataclass
class SensorCapabilities:
    """Co sensor potrafi."""

    # Rozdzielczosc
    max_resolution: Tuple[int, int]  # (width, height)
    supported_resolutions: List[Tuple[int, int]]

    # Framerate
    max_fps: float
    supported_fps: List[float]

    # Tryby
    supported_modes: List[VisionMode]
    # VisionMode: DAYLIGHT, LOWLIGHT, NIGHT, IR, THERMAL, HDR

    # Funkcje
    has_autofocus: bool
    has_zoom: bool
    zoom_range: Optional[Tuple[float, float]]
    has_pan_tilt: bool

    # Jakosciowe
    dynamic_range_db: float
    low_light_sensitivity: float  # 0-1
    color_depth: int  # bits
```

### SensorHealth - graceful degradation

```python
@dataclass
class SensorHealth:
    """
    Stan zdrowia sensora - klucz do graceful degradation.

    Zamiast "dziala/nie dziala" mamy spectrum stanow.
    """

    # Ogolny stan (0.0 = martwy, 1.0 = idealny)
    overall: float

    # Szczegolowe komponenty
    connection: float      # 0-1: polaczenie fizyczne/sieciowe
    stream: float         # 0-1: ciaglosc streamu
    resolution: float     # 0-1: vs maksymalna
    color: float          # 0-1: poprawnosc kolorow
    focus: float          # 0-1: ostrosc obrazu
    exposure: float       # 0-1: poprawnosc ekspozycji
    noise: float          # 0-1: poziom szumu (1=brak szumu)
    latency_ms: float     # opoznienie

    # Problemy
    issues: List[SensorIssue]
    # SensorIssue: DISCONNECTED, LOW_FPS, OVEREXPOSED,
    #              UNDEREXPOSED, BLURRY, NOISY, FROZEN,
    #              COLOR_SHIFT, PARTIAL_FRAME

    def to_human_description(self) -> str:
        """
        Opis dla Marii - jak mowi o swoim wzroku.

        Examples:
            overall=1.0: "Widze wyraznie i ostro"
            overall=0.7: "Widze, ale obraz jest troche rozmyty"
            overall=0.4: "Widze bardzo slabo, duzo szumu"
            overall=0.1: "Ledwo rozpoznaje swiatlo od ciemnosci"
            overall=0.0: "Nie widze nic - moje oko nie dziala"
        """
        ...
```

---

## 4. Preprocessing Layer

### Cel: Normalizacja i ocena jakosci

```python
class VisionPreprocessor:
    """
    Wstepne przetwarzanie obrazu - jak siatkówka.

    Zadania:
    1. Normalizacja (rozdzielczosc, format, orientacja)
    2. Korekcja (balans bieli, ekspozycja, denoising)
    3. Ocena jakosci (czy obraz nadaje sie do analizy)
    4. Detekcja degradacji (co jest nie tak)
    """

    def process(self, raw_frame: Frame) -> ProcessedFrame:
        """
        Przetworz surowa klatke.

        Returns:
            ProcessedFrame z:
            - normalized_image: znormalizowany obraz
            - quality_score: 0-1
            - degradation_flags: co jest nie tak
            - processing_time_ms: czas przetwarzania
        """
        ...

    def assess_quality(self, frame: Frame) -> QualityAssessment:
        """
        Ocen jakosc obrazu bez modyfikacji.

        Metryki:
        - sharpness: ostrosc (Laplacian variance)
        - brightness: jasnosc (mean luminance)
        - contrast: kontrast (std dev)
        - noise_level: poziom szumu
        - color_balance: balans kolorow
        - motion_blur: rozmycie ruchowe
        """
        ...
```

### Degradation Detection

```python
class DegradationDetector:
    """
    Wykrywanie i klasyfikacja problemow z obrazem.

    Pozwala Marii wiedziec CO jest nie tak,
    nie tylko ZE cos jest nie tak.
    """

    def detect(self, frame: Frame) -> List[Degradation]:
        """
        Wykryj wszystkie problemy z obrazem.

        Degradation types:
        - TOTAL_BLACK: calkowita ciemnosc
        - TOTAL_WHITE: przeswietlenie
        - FROZEN: obraz zamrozony (identyczny do poprzedniego)
        - PARTIAL_FRAME: niekompletna klatka
        - HEAVY_NOISE: duzo szumu
        - MOTION_BLUR: rozmycie ruchowe
        - FOCUS_BLUR: rozmycie ostrosci
        - COLOR_SHIFT: przesuniecie kolorow
        - LOW_CONTRAST: niski kontrast
        - ARTIFACTS: artefakty kompresji
        - OCCLUSION: cos zaslania obiektyw
        """
        ...

    def suggest_recovery(self, degradation: Degradation) -> RecoveryAction:
        """
        Zaproponuj jak naprawic problem.

        RecoveryAction:
        - RETRY_CAPTURE: sprobuj ponownie
        - SWITCH_MODE: zmien tryb (np. na night)
        - REDUCE_RESOLUTION: zmniejsz rozdzielczosc
        - INCREASE_EXPOSURE: zwieksz ekspozycje
        - CLEAN_LENS: powiadom o zabrudzeniu obiektywu
        - RESTART_SENSOR: zrestartuj sensor
        - FALLBACK_SENSOR: przelacz na zapasowy sensor
        - ACCEPT_DEGRADED: zaakceptuj gorsza jakosc
        """
        ...
```

---

## 5. Vision Modules (wymienny backend AI)

### Abstrakcyjny interfejs

```python
class VisionModule(Protocol):
    """
    Bazowy interfejs dla modulow analizy wizualnej.

    Kazdy modul (Face, Scene, OCR, Motion) implementuje
    ten interfejs, ale z wlasnym OutputType.
    """

    @property
    def module_name(self) -> str: ...

    @property
    def required_quality(self) -> float:
        """Minimalna jakosc obrazu do dzialania (0-1)."""
        ...

    @property
    def can_work_degraded(self) -> bool:
        """Czy modul moze dzialac z gorszym obrazem."""
        ...

    def analyze(
        self,
        frame: ProcessedFrame,
        context: Optional[VisionContext] = None
    ) -> ModuleOutput:
        """
        Analizuj obraz.

        Args:
            frame: Przetworzony obraz
            context: Kontekst (poprzednie klatki, znane osoby, etc.)

        Returns:
            Wynik analizy (specyficzny dla modulu)
        """
        ...

    def analyze_degraded(
        self,
        frame: ProcessedFrame,
        degradations: List[Degradation]
    ) -> Optional[ModuleOutput]:
        """
        Analizuj mimo degradacji - graceful degradation.

        Moze zwrocic czesciowy wynik lub None.
        """
        ...
```

### Face Module

```python
@dataclass
class FaceModuleOutput:
    """Wynik analizy twarzy."""

    faces_detected: int
    faces: List[FaceData]

    @dataclass
    class FaceData:
        # Lokalizacja
        bounding_box: Tuple[int, int, int, int]
        landmarks: Optional[Dict[str, Tuple[int, int]]]

        # Identyfikacja
        identity: Optional[str]  # "Eryk", "unknown", None
        identity_confidence: float

        # Emocje (opcjonalne)
        emotion: Optional[str]
        emotion_confidence: float

        # Uwaga
        looking_at_camera: bool
        eye_contact: bool

        # Jakosc detekcji
        detection_confidence: float

class FaceModule(VisionModule):
    """
    Modul rozpoznawania twarzy.

    Backend options:
    - Local: face_recognition library
    - Local: InsightFace
    - Ollama: LLaVA dla opisu
    - External: dedykowany serwer
    """

    required_quality = 0.5  # Moze dzialac z gorszym obrazem
    can_work_degraded = True

    def __init__(self, backend: FaceBackend):
        self.backend = backend
        self.known_faces: Dict[str, FaceEmbedding] = {}

    def register_face(self, name: str, images: List[Frame]) -> bool:
        """Zarejestruj nowa osobe."""
        ...

    def analyze_degraded(self, frame, degradations) -> Optional[FaceModuleOutput]:
        """
        Graceful degradation:
        - Wysoki szum: tylko detekcja, bez identyfikacji
        - Niski kontrast: zwieksz kontrast przed analiza
        - Motion blur: uzyj poprzedniej klatki jako referencji
        """
        ...
```

### Scene Module

```python
@dataclass
class SceneModuleOutput:
    """Wynik analizy sceny."""

    # Opis sceny
    scene_type: str  # "living_room", "office", "outdoor", etc.
    scene_description: str  # Natural language

    # Obiekty
    objects: List[DetectedObject]

    @dataclass
    class DetectedObject:
        label: str
        confidence: float
        bounding_box: Tuple[int, int, int, int]
        attributes: Dict[str, Any]  # color, size, state

    # Przestrzen
    depth_estimation: Optional[np.ndarray]
    layout: Optional[RoomLayout]

    # Kontekst
    lighting: str  # "bright", "dim", "dark"
    time_of_day_guess: str  # "day", "evening", "night"
    activity_detected: Optional[str]  # "person_sitting", "movement"

class SceneModule(VisionModule):
    """
    Modul analizy sceny.

    Backend options:
    - Ollama LLaVA: opis naturalny
    - YOLO: detekcja obiektow
    - Depth estimation models
    - Kombinacja powyzszych
    """

    required_quality = 0.3  # Moze dzialac nawet z bardzo slabym obrazem
    can_work_degraded = True
```

### OCR Module

```python
@dataclass
class OCRModuleOutput:
    """Wynik analizy tekstu."""

    text_regions: List[TextRegion]
    full_text: str

    @dataclass
    class TextRegion:
        bounding_box: Tuple[int, int, int, int]
        text: str
        confidence: float
        language: str

        # Typ tekstu
        text_type: str  # "printed", "handwritten", "screen"

        # Formatowanie (jesli wykryte)
        is_heading: bool
        is_list_item: bool

class OCRModule(VisionModule):
    """
    Modul OCR.

    Backend options:
    - Tesseract (local)
    - EasyOCR (local)
    - PaddleOCR (local)
    - Ollama LLaVA (dla opisu dokumentow)
    """

    required_quality = 0.6  # Potrzebuje lepszej jakosci
    can_work_degraded = False  # OCR bez jakosci nie ma sensu
```

### Motion Module

```python
@dataclass
class MotionModuleOutput:
    """Wynik analizy ruchu."""

    motion_detected: bool
    motion_level: float  # 0-1

    # Regiony ruchu
    motion_regions: List[MotionRegion]

    @dataclass
    class MotionRegion:
        bounding_box: Tuple[int, int, int, int]
        velocity: Tuple[float, float]  # pixels/frame
        direction: float  # degrees

    # Klasyfikacja
    motion_type: str  # "person_walking", "object_moving", "camera_shake"

    # Bezpieczenstwo
    is_suspicious: bool
    alert_level: str  # "none", "attention", "warning", "danger"

class MotionModule(VisionModule):
    """
    Modul detekcji ruchu.

    Techniki:
    - Frame differencing
    - Optical flow
    - Background subtraction
    """

    required_quality = 0.2  # Dziala nawet z bardzo slabym obrazem
    can_work_degraded = True
```

---

## 6. Vision Cortex - integracja

### Unified Vision Output

```python
@dataclass
class VisionPercept:
    """
    Zunifikowana percepcja wizualna - to widzi Maria.

    Integruje wyniki wszystkich modulow w jedna,
    spojne reprezentacje tego co Maria "widzi".
    """

    timestamp: float

    # Stan wzroku
    vision_health: SensorHealth
    vision_mode: VisionMode
    quality: float

    # Wyniki modulow (opcjonalne - zaleznie od jakosci)
    faces: Optional[FaceModuleOutput]
    scene: Optional[SceneModuleOutput]
    text: Optional[OCRModuleOutput]
    motion: Optional[MotionModuleOutput]

    # Podsumowanie dla swiadomosci
    summary: str  # Natural language summary
    attention_point: Optional[Tuple[int, int]]  # Gdzie patrzec

    # Alerty
    alerts: List[VisionAlert]

    def to_consciousness_input(self) -> Dict[str, Any]:
        """
        Przeksztalc na input dla Maria Consciousness.

        Uzywa dual format: human + technical.
        """
        human = self._generate_human_description()
        technical = self._generate_technical_data()
        return {
            "human": human,
            "technical": technical,
            "raw": self
        }

    def _generate_human_description(self) -> str:
        """
        Jak Maria opisuje co widzi.

        Examples:
            "Widze Eryka siedzacego przy biurku. Wyglada na skupionego."
            "Widze cos sie rusza w rogu pokoju, ale obraz jest rozmyty."
            "Widze bardzo slabo - chyba jest ciemno lub cos zaslania mi obiektyw."
        """
        ...
```

### Vision Cortex (integration hub)

```python
class VisionCortex:
    """
    Centralny integrator percepcji wizualnej.

    Koordynuje:
    - Sensory (camera abstraction)
    - Preprocessing
    - Moduly analizy
    - Attention mechanism
    - Memory binding
    """

    def __init__(
        self,
        sensors: List[VisionSensor],
        modules: Dict[str, VisionModule],
        attention: AttentionMechanism,
    ):
        self.sensors = sensors
        self.active_sensor: Optional[VisionSensor] = None
        self.modules = modules
        self.attention = attention
        self.preprocessor = VisionPreprocessor()

        # Stan
        self._last_percept: Optional[VisionPercept] = None
        self._health_history: List[SensorHealth] = []

    def perceive(self) -> VisionPercept:
        """
        Glowna funkcja percepcji - jeden "tick" widzenia.

        Pipeline:
        1. Wybierz najlepszy sensor
        2. Pobierz klatke
        3. Preprocessing + ocena jakosci
        4. Uruchom moduly (rownolegle, z uwzglednieniem jakosci)
        5. Zintegruj wyniki
        6. Zaktualizuj attention
        7. Zwroc VisionPercept
        """
        ...

    def _select_best_sensor(self) -> VisionSensor:
        """
        Wybierz najlepszy dzialajacy sensor.

        Graceful degradation: jesli glowny nie dziala,
        przelacz na zapasowy.
        """
        ...

    def _run_modules_adaptive(
        self,
        frame: ProcessedFrame,
        quality: float
    ) -> Dict[str, ModuleOutput]:
        """
        Uruchom moduly adaptacyjnie - zalezne od jakosci.

        Wysoka jakosc: wszystkie moduly
        Srednia: podstawowe moduly
        Niska: tylko motion detection
        Bardzo niska: tylko light/dark detection
        """
        ...
```

---

## 7. Vision Modes

### Tryby pracy kamery

```python
class VisionMode(Enum):
    """Tryby pracy systemu wizualnego."""

    # Standardowe
    DAYLIGHT = "daylight"          # Normalne oswietlenie
    LOWLIGHT = "lowlight"          # Slabe oswietlenie (wzmocnienie)
    NIGHT = "night"                # Tryb nocny (IR / long exposure)

    # Specjalne
    HDR = "hdr"                    # High Dynamic Range
    THERMAL = "thermal"            # Kamera termowizyjna
    IR = "ir"                      # Podczerwien

    # Adaptacyjne
    AUTO = "auto"                  # Automatyczny dobor
    MOTION_PRIORITY = "motion"     # Priorytet detekcji ruchu (wysoki FPS)
    DETAIL_PRIORITY = "detail"     # Priorytet szczegulow (wysoka rozdzielczosc)

class VisionModeManager:
    """
    Zarzadzanie trybami - automatyczna adaptacja.
    """

    def assess_conditions(self, frame: Frame) -> LightingConditions:
        """Ocen warunki oswietleniowe."""
        ...

    def recommend_mode(
        self,
        conditions: LightingConditions,
        task: VisionTask
    ) -> VisionMode:
        """
        Zaproponuj optymalny tryb.

        Np.:
        - Ciemno + motion detection = NIGHT + MOTION_PRIORITY
        - Jasno + OCR = DAYLIGHT + DETAIL_PRIORITY
        - Bardzo jasno = HDR
        """
        ...

    def transition_mode(
        self,
        sensor: VisionSensor,
        from_mode: VisionMode,
        to_mode: VisionMode
    ) -> bool:
        """
        Plynne przejscie miedzy trybami.

        Unika nagłych zmian jasnosci ktore moga "oslepic".
        """
        ...
```

---

## 8. Attention Mechanism

### Inspiracja biologiczna

```python
class AttentionMechanism:
    """
    Mechanizm uwagi - jak fovea w oku.

    Biologiczne oko nie przetwarza calego pola widzenia
    z ta sama dokladnoscia - centrum jest ostre (fovea),
    peryferia sa rozmyte ale wykrywaja ruch.

    Implementacja:
    - Attention point: gdzie Maria "patrzy"
    - Saliency map: co przyciaga uwage
    - Priority queue: co analizowac najpierw
    """

    def __init__(self):
        self.attention_point: Tuple[int, int] = (0.5, 0.5)  # Normalized
        self.saliency_map: Optional[np.ndarray] = None
        self.attention_history: List[Tuple[float, float]] = []

    def compute_saliency(self, frame: Frame) -> np.ndarray:
        """
        Oblicz mape istotnosci.

        Co przyciaga uwage:
        - Ruch (najwyzszy priorytet)
        - Twarze
        - Tekst
        - Jasne/kontrastowe regiony
        - Nieoczekiwane zmiany
        """
        ...

    def update_attention(
        self,
        saliency_map: np.ndarray,
        detections: Dict[str, Any],
        context: VisionContext
    ) -> Tuple[int, int]:
        """
        Zaktualizuj punkt uwagi.

        Bierze pod uwage:
        - Saliency map
        - Wykryte obiekty/twarze
        - Kontekst (np. Eryk mowil, wiec patrz na niego)
        - Historia (nie skakaj chaotycznie)
        """
        ...

    def get_foveal_region(self) -> Tuple[int, int, int, int]:
        """
        Pobierz region wysokiej ostrosci (centrum uwagi).

        Ten region jest analizowany z wieksza dokladnoscia.
        """
        ...
```

---

## 9. Integracja z Maria Consciousness

### VisionPercept -> Unified Perception

```python
class VisionPerceptionAdapter:
    """
    Adapter integrujacy VisionCortex z Maria Consciousness.

    Przeksztalca VisionPercept na format zgodny z
    Unified Perception z CONSCIOUSNESS_SPEC.md.
    """

    def adapt(self, percept: VisionPercept) -> Dict[str, Any]:
        """
        Przeksztalc percepcje wizualna na input dla swiadomosci.

        Output format (dual):
        {
            "human": "Widze Eryka przy biurku, wyglada na zajętego.",
            "technical": {
                "faces": [...],
                "objects": [...],
                "motion": {...},
                "quality": 0.85,
                "mode": "DAYLIGHT"
            },
            "alerts": [...],
            "attention": (0.3, 0.4)
        }
        """
        ...
```

### Proaktywne powiadomienia

```python
class VisionAlertSystem:
    """
    System alertow wizualnych.

    Maria proaktywnie informuje o:
    - Wykryciu osoby (nowej/znanej)
    - Podejrzanym ruchu
    - Problemach z widzeniem
    - Zmianach w otoczeniu
    """

    def check_alerts(self, percept: VisionPercept) -> List[VisionAlert]:
        """
        Sprawdz czy sa powody do alertu.
        """
        alerts = []

        # Nowa osoba
        if percept.faces and any(f.identity == "unknown" for f in percept.faces.faces):
            alerts.append(VisionAlert(
                type="new_person",
                priority="attention",
                message="Widze kogos kogo nie znam"
            ))

        # Podejrzany ruch
        if percept.motion and percept.motion.is_suspicious:
            alerts.append(VisionAlert(
                type="suspicious_motion",
                priority="warning",
                message="Wykrylam podejrzany ruch"
            ))

        # Problemy z widzeniem
        if percept.vision_health.overall < 0.5:
            alerts.append(VisionAlert(
                type="vision_degraded",
                priority="info",
                message=percept.vision_health.to_human_description()
            ))

        return alerts
```

---

## 10. Implementacja - fazy (systematyczne podejscie)

> **Zasada:** Wolniej, ale dokladniej. Kazda faza musi byc w pelni przetestowana
> przed przejsciem do nastepnej. Brak skrotow typu MVP.

### Faza 1: Sensor Abstraction Layer

**Cel:** Solidne fundamenty - abstrakcja sensorow z graceful degradation.

**Struktura:**
```
agent_core/vision/
├── __init__.py
├── sensors/
│   ├── __init__.py
│   ├── base.py              # VisionSensor protocol
│   ├── capabilities.py      # SensorCapabilities dataclass
│   ├── health.py            # SensorHealth + degradation levels
│   ├── usb_webcam.py        # USB camera implementation
│   ├── ip_camera.py         # IP/RTSP camera (placeholder)
│   └── mock_sensor.py       # For testing
├── models.py                # Frame, VisionMode, enums
└── tests/
    ├── __init__.py
    ├── test_health.py       # Testy graceful degradation
    ├── test_mock_sensor.py
    └── test_usb_webcam.py   # Testy z prawdziwa kamera
```

**Deliverables:**
- [ ] `VisionSensor` protocol z pelna dokumentacja
- [ ] `SensorCapabilities` - co sensor potrafi
- [ ] `SensorHealth` z 7 poziomami degradacji (100% -> 5%)
- [ ] `SensorIssue` enum (wszystkie mozliwe problemy)
- [ ] `MockSensor` do testow (symuluje rozne awarie)
- [ ] `USBWebcamSensor` - implementacja dla USB kamer
- [ ] Testy: min. 30 test cases dla graceful degradation
- [ ] Dokumentacja: jak dodac nowy typ sensora

**Kryteria ukonczenia:**
- Wszystkie testy przechodza
- MockSensor moze symulowac kazdy poziom degradacji
- USBWebcam dziala z prawdziwa kamera
- Maria moze powiedziec "widze dobrze/slabo/bardzo slabo/nic"

---

### Faza 2: Preprocessing Layer

**Cel:** Ocena jakosci obrazu i detekcja problemow.

**Struktura:**
```
agent_core/vision/
├── preprocessing/
│   ├── __init__.py
│   ├── quality.py           # QualityAssessment
│   ├── degradation.py       # DegradationDetector
│   ├── normalizer.py        # Normalizacja obrazu
│   ├── recovery.py          # RecoveryAction suggestions
│   └── metrics.py           # Sharpness, brightness, noise metrics
└── tests/
    ├── test_quality.py
    ├── test_degradation.py
    └── test_normalizer.py
```

**Deliverables:**
- [ ] `QualityAssessment` - ocena jakosci (sharpness, brightness, contrast, noise)
- [ ] `DegradationDetector` - wykrywanie 12+ typow problemow
- [ ] `RecoveryAction` - sugestie naprawy
- [ ] `VisionPreprocessor` - glowna klasa przetwarzania
- [ ] Metryki: Laplacian variance, histogram analysis, noise estimation
- [ ] Testy z obrazami testowymi (rozne typy degradacji)
- [ ] Benchmark: czas przetwarzania < 50ms na klatke

**Kryteria ukonczenia:**
- Poprawna detekcja wszystkich 12 typow degradacji
- Sensowne sugestie naprawy dla kazdego typu
- Maria wie CO jest nie tak, nie tylko ZE cos jest nie tak

---

### Faza 3: Vision Modules

**Cel:** Moduly analizy obrazu z wymiennymi backendami.

**Struktura:**
```
agent_core/vision/
├── modules/
│   ├── __init__.py
│   ├── base.py              # VisionModule protocol
│   ├── motion/
│   │   ├── __init__.py
│   │   ├── detector.py      # MotionModule
│   │   ├── frame_diff.py    # Frame differencing backend
│   │   └── optical_flow.py  # Optical flow backend
│   ├── scene/
│   │   ├── __init__.py
│   │   ├── analyzer.py      # SceneModule
│   │   ├── yolo_backend.py  # YOLO object detection
│   │   └── llava_backend.py # LLaVA description
│   ├── ocr/
│   │   ├── __init__.py
│   │   ├── reader.py        # OCRModule
│   │   ├── tesseract.py     # Tesseract backend
│   │   └── easyocr.py       # EasyOCR backend
│   └── face/
│       ├── __init__.py
│       ├── recognizer.py    # FaceModule
│       ├── detection.py     # Face detection only
│       ├── embedding.py     # Face embeddings
│       └── known_faces.py   # Database znanych twarzy
└── tests/
    ├── test_motion.py
    ├── test_scene.py
    ├── test_ocr.py
    └── test_face.py
```

**Deliverables per module:**

**Motion Module:**
- [ ] Frame differencing (prosty, szybki)
- [ ] Optical flow (dokladniejszy)
- [ ] Klasyfikacja ruchu (osoba/obiekt/kamera)
- [ ] Alert levels (none/attention/warning/danger)
- [ ] Graceful degradation: dziala nawet przy quality=0.2

**Scene Module:**
- [ ] YOLO backend (obiekty)
- [ ] LLaVA backend (opis naturalny)
- [ ] Depth estimation (opcjonalne)
- [ ] Lighting/time-of-day detection
- [ ] Graceful degradation: opis ogolny przy slabej jakosci

**OCR Module:**
- [ ] Tesseract backend
- [ ] EasyOCR backend
- [ ] Region detection (gdzie jest tekst)
- [ ] Language detection
- [ ] Graceful degradation: NIE dziala przy slabej jakosci (wymaga quality>0.6)

**Face Module:**
- [ ] Detekcja twarzy (bounding boxes)
- [ ] Landmarks (oczy, nos, usta)
- [ ] Embeddings (wektory cech)
- [ ] Rozpoznawanie (porownanie z baza)
- [ ] Rejestracja nowych osob
- [ ] Emocje (opcjonalne)
- [ ] Graceful degradation: tylko detekcja przy slabej jakosci

**Kryteria ukonczenia:**
- Kazdy modul ma min. 2 wymienne backendy
- Testy z prawdziwymi obrazami
- Dokumentacja: jak dodac nowy backend

---

### Faza 4: Vision Cortex (integracja)

**Cel:** Zintegrowana percepcja wizualna jako jeden "zmysl".

**Struktura:**
```
agent_core/vision/
├── cortex.py                # VisionCortex - glowny integrator
├── attention.py             # AttentionMechanism
├── modes.py                 # VisionModeManager
├── percept.py               # VisionPercept - unified output
├── adapter.py               # Integration with Consciousness
├── alerts.py                # VisionAlertSystem
└── tests/
    ├── test_cortex.py
    ├── test_attention.py
    └── test_integration.py
```

**Deliverables:**
- [ ] `VisionCortex` - koordynator wszystkich komponentow
- [ ] `AttentionMechanism` - gdzie Maria "patrzy"
- [ ] `VisionModeManager` - automatyczna zmiana trybow
- [ ] `VisionPercept` - zunifikowany output
- [ ] `VisionAlertSystem` - proaktywne powiadomienia
- [ ] Adapter do Maria Consciousness (dual format)
- [ ] REPL command: `/vision` (status, preview, etc.)
- [ ] Web UI API: `/api/vision`

**Kryteria ukonczenia:**
- Pipeline dziala end-to-end
- Maria moze opisac co widzi w naturalnym jezyku
- Graceful degradation na kazdym poziomie
- Integracja ze swiadomoscia (Unified Perception)

---

## 11. Testowanie

### Unit tests

```python
def test_graceful_degradation():
    """Sensor z problemami nadal zwraca czesciowe dane."""
    sensor = MockSensor(health=0.3, issues=[SensorIssue.HEAVY_NOISE])
    frame = sensor.capture_frame()

    assert frame is not None
    assert frame.quality < 0.5
    assert SensorIssue.HEAVY_NOISE in frame.degradations

def test_module_fallback():
    """Modul przechodzi w tryb degraded przy slabej jakosci."""
    module = FaceModule(backend=MockBackend())

    # Dobra jakosc - pelna analiza
    good_frame = ProcessedFrame(quality=0.9)
    result = module.analyze(good_frame)
    assert result.faces is not None

    # Slaba jakosc - tylko detekcja (bez identyfikacji)
    bad_frame = ProcessedFrame(quality=0.3)
    result = module.analyze_degraded(bad_frame, [Degradation.HEAVY_NOISE])
    assert result.faces_detected >= 0
    assert all(f.identity is None for f in result.faces)
```

### Integration tests

```python
def test_full_perception_pipeline():
    """Caly pipeline od sensora do VisionPercept."""
    cortex = VisionCortex(
        sensors=[MockSensor()],
        modules={"motion": MotionModule(), "scene": SceneModule()},
        attention=AttentionMechanism()
    )

    percept = cortex.perceive()

    assert percept.vision_health.overall > 0
    assert percept.summary is not None
    assert percept.motion is not None or percept.scene is not None
```

---

## 12. Przyszle rozszerzenia

### Multi-camera fusion

```
- Wiele kamer -> jedno spojne widzenie
- Stereoskopia (gleboksc)
- 360 stopni
```

### Learning

```
- Uczenie sie nowych twarzy
- Uczenie sie normalnego stanu pokoju
- Anomaly detection
```

### Integration with other senses

```
- Vision + Audio: rozpoznawanie kto mowi
- Vision + Motion sensors: weryfikacja
- Vision + Time: patterns (kto przychodzi o ktorej)
```

---

*Ten dokument definiuje architekture. Szczegolowa implementacja kazdego modulu powinna byc opracowana osobno, z uwzglednieniem wybranego backendu AI.*
