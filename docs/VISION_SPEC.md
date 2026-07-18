# M.A.R.I.A. - Visual Perception Specification (The Eye)

> **Created:** 2026-02-01
> **Status:** Architecture to be developed
> **Philosophy:** The eye as an organ, not a device - graceful degradation instead of 0/1
> **Approach:** Slower, but more thorough. Every phase fully tested.

---

## 1. Guiding principle: Biological inspiration

### The human eye vs. a digital camera

| Aspect | Digital camera | Human eye | M.A.R.I.A. Vision |
|--------|----------------|-------------|-------------------|
| Failure | 0 or 1 (works/doesn't work) | Graceful degradation | Graceful degradation |
| Adaptation | None / manual | Automatic (pupil) | Multi-mode adaptation |
| Processing | Raw image | Pre-processed in the retina | Edge preprocessing |
| Attention | Entire frame equal | Fovea (sharp center) | Attention mechanism |
| Pain | None | Signals a problem | Health alerts |

### Graceful Degradation - the key principle

```
FULL VISION (100%)
    |
    v color damage
GRAYSCALE VISION (80%)
    |
    v resolution damage
LOW-RES VISION (60%)
    |
    v sharpness damage
BLUR DETECTION (40%)
    |
    v stream damage
FRAME-BY-FRAME (20%)
    |
    v sensor damage
LIGHT/DARK ONLY (5%)
    |
    v total failure
BLIND MODE (0%) - other senses only
```

Maria NEVER says "the camera is broken" - she says "I see very poorly" or "I only see light".

---

## 2. Layered architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     MARIA CONSCIOUSNESS                     │
│              (Unified Perception - one "self")              │
├─────────────────────────────────────────────────────────────┤
│                        VISION CORTEX                        │
│     Integration of all visual channels                      │
│     Attention mechanism, memory binding                     │
├──────────────┬──────────────┬──────────────┬────────────────┤
│   FACE       │   SCENE      │   OCR        │   MOTION       │
│   MODULE     │   MODULE     │   MODULE     │   MODULE       │
│              │              │              │                │
│  Faces,      │  Objects,    │  Text,       │  Motion,       │
│  emotions,   │  space,      │  documents,  │  gestures,     │
│  identity    │  context     │  screens     │  danger        │
├──────────────┴──────────────┴──────────────┴────────────────┤
│                     PREPROCESSING LAYER                     │
│     Normalization, denoising, color correction              │
│     Quality assessment, degradation detection               │
├─────────────────────────────────────────────────────────────┤
│                     SENSOR ABSTRACTION                      │
│     Unified interface for all camera types                  │
├──────────┬──────────┬──────────┬──────────┬─────────────────┤
│  USB     │  IP/RTSP │  RPi     │  Thermal │  Future         │
│  Webcam  │  Camera  │  Camera  │  IR      │  sensors...     │
└──────────┴──────────┴──────────┴──────────┴─────────────────┘
```

---

## 3. Sensor Abstraction Layer

### Base interface (protocol)

```python
class VisionSensor(Protocol):
    """
    Abstract interface for all vision sensors.
    Every sensor must implement these methods.
    """

    @property
    def sensor_id(self) -> str:
        """Unique sensor identifier."""
        ...

    @property
    def capabilities(self) -> SensorCapabilities:
        """What the sensor can do (resolution, FPS, modes)."""
        ...

    @property
    def health(self) -> SensorHealth:
        """Sensor health state (0.0-1.0 + details)."""
        ...

    def capture_frame(self) -> Optional[Frame]:
        """
        Capture a single frame.
        Returns None if the sensor is completely non-functional.
        """
        ...

    def get_stream(self) -> Iterator[Frame]:
        """Frame generator (for a continuous stream)."""
        ...

    def set_mode(self, mode: VisionMode) -> bool:
        """Change mode (day/night/IR/etc)."""
        ...

    def diagnose(self) -> DiagnosticReport:
        """Full sensor diagnostics."""
        ...
```

### SensorCapabilities

```python
@dataclass
class SensorCapabilities:
    """What the sensor can do."""

    # Resolution
    max_resolution: Tuple[int, int]  # (width, height)
    supported_resolutions: List[Tuple[int, int]]

    # Framerate
    max_fps: float
    supported_fps: List[float]

    # Modes
    supported_modes: List[VisionMode]
    # VisionMode: DAYLIGHT, LOWLIGHT, NIGHT, IR, THERMAL, HDR

    # Features
    has_autofocus: bool
    has_zoom: bool
    zoom_range: Optional[Tuple[float, float]]
    has_pan_tilt: bool

    # Quality
    dynamic_range_db: float
    low_light_sensitivity: float  # 0-1
    color_depth: int  # bits
```

### SensorHealth - graceful degradation

```python
@dataclass
class SensorHealth:
    """
    Sensor health state - the key to graceful degradation.

    Instead of "works/doesn't work" we have a spectrum of states.
    """

    # Overall state (0.0 = dead, 1.0 = perfect)
    overall: float

    # Detailed components
    connection: float      # 0-1: physical/network connection
    stream: float         # 0-1: stream continuity
    resolution: float     # 0-1: vs maximum
    color: float          # 0-1: color correctness
    focus: float          # 0-1: image sharpness
    exposure: float       # 0-1: exposure correctness
    noise: float          # 0-1: noise level (1=no noise)
    latency_ms: float     # latency

    # Problems
    issues: List[SensorIssue]
    # SensorIssue: DISCONNECTED, LOW_FPS, OVEREXPOSED,
    #              UNDEREXPOSED, BLURRY, NOISY, FROZEN,
    #              COLOR_SHIFT, PARTIAL_FRAME

    def to_human_description(self) -> str:
        """
        Description for Maria - how she talks about her sight.

        Examples:
            overall=1.0: "I see clearly and sharply"
            overall=0.7: "I can see, but the image is a bit blurry"
            overall=0.4: "I see very poorly, a lot of noise"
            overall=0.1: "I can barely tell light from dark"
            overall=0.0: "I see nothing - my eye is not working"
        """
        ...
```

---

## 4. Preprocessing Layer

### Purpose: Normalization and quality assessment

```python
class VisionPreprocessor:
    """
    Image pre-processing - like the retina.

    Tasks:
    1. Normalization (resolution, format, orientation)
    2. Correction (white balance, exposure, denoising)
    3. Quality assessment (whether the image is suitable for analysis)
    4. Degradation detection (what is wrong)
    """

    def process(self, raw_frame: Frame) -> ProcessedFrame:
        """
        Process a raw frame.

        Returns:
            ProcessedFrame with:
            - normalized_image: the normalized image
            - quality_score: 0-1
            - degradation_flags: what is wrong
            - processing_time_ms: processing time
        """
        ...

    def assess_quality(self, frame: Frame) -> QualityAssessment:
        """
        Assess image quality without modification.

        Metrics:
        - sharpness: sharpness (Laplacian variance)
        - brightness: brightness (mean luminance)
        - contrast: contrast (std dev)
        - noise_level: noise level
        - color_balance: color balance
        - motion_blur: motion blur
        """
        ...
```

### Degradation Detection

```python
class DegradationDetector:
    """
    Detection and classification of image problems.

    Lets Maria know WHAT is wrong,
    not just THAT something is wrong.
    """

    def detect(self, frame: Frame) -> List[Degradation]:
        """
        Detect all problems with the image.

        Degradation types:
        - TOTAL_BLACK: complete darkness
        - TOTAL_WHITE: overexposure
        - FROZEN: frozen image (identical to the previous one)
        - PARTIAL_FRAME: incomplete frame
        - HEAVY_NOISE: a lot of noise
        - MOTION_BLUR: motion blur
        - FOCUS_BLUR: focus blur
        - COLOR_SHIFT: color shift
        - LOW_CONTRAST: low contrast
        - ARTIFACTS: compression artifacts
        - OCCLUSION: something is blocking the lens
        """
        ...

    def suggest_recovery(self, degradation: Degradation) -> RecoveryAction:
        """
        Suggest how to fix the problem.

        RecoveryAction:
        - RETRY_CAPTURE: try again
        - SWITCH_MODE: change mode (e.g. to night)
        - REDUCE_RESOLUTION: lower the resolution
        - INCREASE_EXPOSURE: increase exposure
        - CLEAN_LENS: notify about a dirty lens
        - RESTART_SENSOR: restart the sensor
        - FALLBACK_SENSOR: switch to a backup sensor
        - ACCEPT_DEGRADED: accept lower quality
        """
        ...
```

---

## 5. Vision Modules (swappable AI backend)

### Abstract interface

```python
class VisionModule(Protocol):
    """
    Base interface for vision-analysis modules.

    Every module (Face, Scene, OCR, Motion) implements
    this interface, but with its own OutputType.
    """

    @property
    def module_name(self) -> str: ...

    @property
    def required_quality(self) -> float:
        """Minimum image quality required to operate (0-1)."""
        ...

    @property
    def can_work_degraded(self) -> bool:
        """Whether the module can operate with a degraded image."""
        ...

    def analyze(
        self,
        frame: ProcessedFrame,
        context: Optional[VisionContext] = None
    ) -> ModuleOutput:
        """
        Analyze the image.

        Args:
            frame: The processed image
            context: Context (previous frames, known people, etc.)

        Returns:
            Analysis result (module-specific)
        """
        ...

    def analyze_degraded(
        self,
        frame: ProcessedFrame,
        degradations: List[Degradation]
    ) -> Optional[ModuleOutput]:
        """
        Analyze despite degradation - graceful degradation.

        May return a partial result or None.
        """
        ...
```

### Face Module

```python
@dataclass
class FaceModuleOutput:
    """Face analysis result."""

    faces_detected: int
    faces: List[FaceData]

    @dataclass
    class FaceData:
        # Location
        bounding_box: Tuple[int, int, int, int]
        landmarks: Optional[Dict[str, Tuple[int, int]]]

        # Identification
        identity: Optional[str]  # "operator", "unknown", None
        identity_confidence: float

        # Emotions (optional)
        emotion: Optional[str]
        emotion_confidence: float

        # Attention
        looking_at_camera: bool
        eye_contact: bool

        # Detection quality
        detection_confidence: float

class FaceModule(VisionModule):
    """
    Face recognition module.

    Backend options:
    - Local: face_recognition library
    - Local: InsightFace
    - Ollama: LLaVA for description
    - External: dedicated server
    """

    required_quality = 0.5  # Can operate with a degraded image
    can_work_degraded = True

    def __init__(self, backend: FaceBackend):
        self.backend = backend
        self.known_faces: Dict[str, FaceEmbedding] = {}

    def register_face(self, name: str, images: List[Frame]) -> bool:
        """Register a new person."""
        ...

    def analyze_degraded(self, frame, degradations) -> Optional[FaceModuleOutput]:
        """
        Graceful degradation:
        - High noise: detection only, no identification
        - Low contrast: increase contrast before analysis
        - Motion blur: use the previous frame as a reference
        """
        ...
```

### Scene Module

```python
@dataclass
class SceneModuleOutput:
    """Scene analysis result."""

    # Scene description
    scene_type: str  # "living_room", "office", "outdoor", etc.
    scene_description: str  # Natural language

    # Objects
    objects: List[DetectedObject]

    @dataclass
    class DetectedObject:
        label: str
        confidence: float
        bounding_box: Tuple[int, int, int, int]
        attributes: Dict[str, Any]  # color, size, state

    # Space
    depth_estimation: Optional[np.ndarray]
    layout: Optional[RoomLayout]

    # Context
    lighting: str  # "bright", "dim", "dark"
    time_of_day_guess: str  # "day", "evening", "night"
    activity_detected: Optional[str]  # "person_sitting", "movement"

class SceneModule(VisionModule):
    """
    Scene analysis module.

    Backend options:
    - Ollama LLaVA: natural-language description
    - YOLO: object detection
    - Depth estimation models
    - A combination of the above
    """

    required_quality = 0.3  # Can operate even with a very poor image
    can_work_degraded = True
```

### OCR Module

```python
@dataclass
class OCRModuleOutput:
    """Text analysis result."""

    text_regions: List[TextRegion]
    full_text: str

    @dataclass
    class TextRegion:
        bounding_box: Tuple[int, int, int, int]
        text: str
        confidence: float
        language: str

        # Text type
        text_type: str  # "printed", "handwritten", "screen"

        # Formatting (if detected)
        is_heading: bool
        is_list_item: bool

class OCRModule(VisionModule):
    """
    OCR module.

    Backend options:
    - Tesseract (local)
    - EasyOCR (local)
    - PaddleOCR (local)
    - Ollama LLaVA (for document description)
    """

    required_quality = 0.6  # Needs higher quality
    can_work_degraded = False  # OCR without quality makes no sense
```

### Motion Module

```python
@dataclass
class MotionModuleOutput:
    """Motion analysis result."""

    motion_detected: bool
    motion_level: float  # 0-1

    # Motion regions
    motion_regions: List[MotionRegion]

    @dataclass
    class MotionRegion:
        bounding_box: Tuple[int, int, int, int]
        velocity: Tuple[float, float]  # pixels/frame
        direction: float  # degrees

    # Classification
    motion_type: str  # "person_walking", "object_moving", "camera_shake"

    # Safety
    is_suspicious: bool
    alert_level: str  # "none", "attention", "warning", "danger"

class MotionModule(VisionModule):
    """
    Motion detection module.

    Techniques:
    - Frame differencing
    - Optical flow
    - Background subtraction
    """

    required_quality = 0.2  # Works even with a very poor image
    can_work_degraded = True
```

---

## 6. Vision Cortex - integration

### Unified Vision Output

```python
@dataclass
class VisionPercept:
    """
    Unified visual perception - this is what Maria sees.

    Integrates the results of all modules into a single,
    coherent representation of what Maria "sees".
    """

    timestamp: float

    # Vision state
    vision_health: SensorHealth
    vision_mode: VisionMode
    quality: float

    # Module results (optional - depending on quality)
    faces: Optional[FaceModuleOutput]
    scene: Optional[SceneModuleOutput]
    text: Optional[OCRModuleOutput]
    motion: Optional[MotionModuleOutput]

    # Summary for consciousness
    summary: str  # Natural language summary
    attention_point: Optional[Tuple[int, int]]  # Where to look

    # Alerts
    alerts: List[VisionAlert]

    def to_consciousness_input(self) -> Dict[str, Any]:
        """
        Transform into input for Maria Consciousness.

        Uses a dual format: human + technical.
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
        How Maria describes what she sees.

        Examples:
            "I see the operator sitting at the desk. He looks focused."
            "I see something moving in the corner of the room, but the image is blurry."
            "I see very poorly - it's probably dark or something is blocking my lens."
        """
        ...
```

### Vision Cortex (integration hub)

```python
class VisionCortex:
    """
    Central integrator of visual perception.

    Coordinates:
    - Sensors (camera abstraction)
    - Preprocessing
    - Analysis modules
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

        # State
        self._last_percept: Optional[VisionPercept] = None
        self._health_history: List[SensorHealth] = []

    def perceive(self) -> VisionPercept:
        """
        The main perception function - one "tick" of seeing.

        Pipeline:
        1. Select the best sensor
        2. Capture a frame
        3. Preprocessing + quality assessment
        4. Run the modules (in parallel, taking quality into account)
        5. Integrate the results
        6. Update attention
        7. Return VisionPercept
        """
        ...

    def _select_best_sensor(self) -> VisionSensor:
        """
        Select the best working sensor.

        Graceful degradation: if the primary one fails,
        switch to a backup.
        """
        ...

    def _run_modules_adaptive(
        self,
        frame: ProcessedFrame,
        quality: float
    ) -> Dict[str, ModuleOutput]:
        """
        Run the modules adaptively - depending on quality.

        High quality: all modules
        Medium: basic modules
        Low: motion detection only
        Very low: light/dark detection only
        """
        ...
```

---

## 7. Vision Modes

### Camera operating modes

```python
class VisionMode(Enum):
    """Operating modes of the vision system."""

    # Standard
    DAYLIGHT = "daylight"          # Normal lighting
    LOWLIGHT = "lowlight"          # Low lighting (amplification)
    NIGHT = "night"                # Night mode (IR / long exposure)

    # Special
    HDR = "hdr"                    # High Dynamic Range
    THERMAL = "thermal"            # Thermal camera
    IR = "ir"                      # Infrared

    # Adaptive
    AUTO = "auto"                  # Automatic selection
    MOTION_PRIORITY = "motion"     # Motion detection priority (high FPS)
    DETAIL_PRIORITY = "detail"     # Detail priority (high resolution)

class VisionModeManager:
    """
    Mode management - automatic adaptation.
    """

    def assess_conditions(self, frame: Frame) -> LightingConditions:
        """Assess lighting conditions."""
        ...

    def recommend_mode(
        self,
        conditions: LightingConditions,
        task: VisionTask
    ) -> VisionMode:
        """
        Suggest the optimal mode.

        E.g.:
        - Dark + motion detection = NIGHT + MOTION_PRIORITY
        - Bright + OCR = DAYLIGHT + DETAIL_PRIORITY
        - Very bright = HDR
        """
        ...

    def transition_mode(
        self,
        sensor: VisionSensor,
        from_mode: VisionMode,
        to_mode: VisionMode
    ) -> bool:
        """
        Smooth transition between modes.

        Avoids sudden brightness changes that could "blind".
        """
        ...
```

---

## 8. Attention Mechanism

### Biological inspiration

```python
class AttentionMechanism:
    """
    Attention mechanism - like the fovea in the eye.

    The biological eye does not process the entire field of view
    with the same precision - the center is sharp (fovea),
    the periphery is blurry but detects motion.

    Implementation:
    - Attention point: where Maria "looks"
    - Saliency map: what draws attention
    - Priority queue: what to analyze first
    """

    def __init__(self):
        self.attention_point: Tuple[int, int] = (0.5, 0.5)  # Normalized
        self.saliency_map: Optional[np.ndarray] = None
        self.attention_history: List[Tuple[float, float]] = []

    def compute_saliency(self, frame: Frame) -> np.ndarray:
        """
        Compute the saliency map.

        What draws attention:
        - Motion (highest priority)
        - Faces
        - Text
        - Bright/high-contrast regions
        - Unexpected changes
        """
        ...

    def update_attention(
        self,
        saliency_map: np.ndarray,
        detections: Dict[str, Any],
        context: VisionContext
    ) -> Tuple[int, int]:
        """
        Update the attention point.

        Takes into account:
        - Saliency map
        - Detected objects/faces
        - Context (e.g. the operator spoke, so look at him)
        - History (don't jump around chaotically)
        """
        ...

    def get_foveal_region(self) -> Tuple[int, int, int, int]:
        """
        Get the high-sharpness region (center of attention).

        This region is analyzed with greater precision.
        """
        ...
```

---

## 9. Integration with Maria Consciousness

### VisionPercept -> Unified Perception

```python
class VisionPerceptionAdapter:
    """
    Adapter integrating VisionCortex with Maria Consciousness.

    Transforms VisionPercept into a format compatible with
    the Unified Perception from CONSCIOUSNESS_SPEC.md.
    """

    def adapt(self, percept: VisionPercept) -> Dict[str, Any]:
        """
        Transform visual perception into input for consciousness.

        Output format (dual):
        {
            "human": "I see the operator at the desk, he looks busy.",
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

### Proactive notifications

```python
class VisionAlertSystem:
    """
    Visual alert system.

    Maria proactively reports:
    - Detection of a person (new/known)
    - Suspicious motion
    - Vision problems
    - Changes in the surroundings
    """

    def check_alerts(self, percept: VisionPercept) -> List[VisionAlert]:
        """
        Check whether there are reasons for an alert.
        """
        alerts = []

        # New person
        if percept.faces and any(f.identity == "unknown" for f in percept.faces.faces):
            alerts.append(VisionAlert(
                type="new_person",
                priority="attention",
                message="I see someone I don't know"
            ))

        # Suspicious motion
        if percept.motion and percept.motion.is_suspicious:
            alerts.append(VisionAlert(
                type="suspicious_motion",
                priority="warning",
                message="I detected suspicious motion"
            ))

        # Vision problems
        if percept.vision_health.overall < 0.5:
            alerts.append(VisionAlert(
                type="vision_degraded",
                priority="info",
                message=percept.vision_health.to_human_description()
            ))

        return alerts
```

---

## 10. Implementation - phases (systematic approach)

> **Principle:** Slower, but more thorough. Every phase must be fully tested
> before moving on to the next. No MVP-style shortcuts.

### Phase 1: Sensor Abstraction Layer

**Goal:** Solid foundations - sensor abstraction with graceful degradation.

**Structure:**
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
    ├── test_health.py       # Graceful degradation tests
    ├── test_mock_sensor.py
    └── test_usb_webcam.py   # Tests with a real camera
```

**Deliverables:**
- [ ] `VisionSensor` protocol with full documentation
- [ ] `SensorCapabilities` - what the sensor can do
- [ ] `SensorHealth` with 7 degradation levels (100% -> 5%)
- [ ] `SensorIssue` enum (all possible problems)
- [ ] `MockSensor` for testing (simulates various failures)
- [ ] `USBWebcamSensor` - implementation for USB cameras
- [ ] Tests: min. 30 test cases for graceful degradation
- [ ] Documentation: how to add a new sensor type

**Completion criteria:**
- All tests pass
- MockSensor can simulate every degradation level
- USBWebcam works with a real camera
- Maria can say "I see well/poorly/very poorly/nothing"

---

### Phase 2: Preprocessing Layer

**Goal:** Image quality assessment and problem detection.

**Structure:**
```
agent_core/vision/
├── preprocessing/
│   ├── __init__.py
│   ├── quality.py           # QualityAssessment
│   ├── degradation.py       # DegradationDetector
│   ├── normalizer.py        # Image normalization
│   ├── recovery.py          # RecoveryAction suggestions
│   └── metrics.py           # Sharpness, brightness, noise metrics
└── tests/
    ├── test_quality.py
    ├── test_degradation.py
    └── test_normalizer.py
```

**Deliverables:**
- [ ] `QualityAssessment` - quality assessment (sharpness, brightness, contrast, noise)
- [ ] `DegradationDetector` - detection of 12+ problem types
- [ ] `RecoveryAction` - recovery suggestions
- [ ] `VisionPreprocessor` - the main processing class
- [ ] Metrics: Laplacian variance, histogram analysis, noise estimation
- [ ] Tests with test images (various degradation types)
- [ ] Benchmark: processing time < 50ms per frame

**Completion criteria:**
- Correct detection of all 12 degradation types
- Sensible recovery suggestions for each type
- Maria knows WHAT is wrong, not just THAT something is wrong

---

### Phase 3: Vision Modules

**Goal:** Image analysis modules with swappable backends.

**Structure:**
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
│       └── known_faces.py   # Database of known faces
└── tests/
    ├── test_motion.py
    ├── test_scene.py
    ├── test_ocr.py
    └── test_face.py
```

**Deliverables per module:**

**Motion Module:**
- [ ] Frame differencing (simple, fast)
- [ ] Optical flow (more accurate)
- [ ] Motion classification (person/object/camera)
- [ ] Alert levels (none/attention/warning/danger)
- [ ] Graceful degradation: works even at quality=0.2

**Scene Module:**
- [ ] YOLO backend (objects)
- [ ] LLaVA backend (natural-language description)
- [ ] Depth estimation (optional)
- [ ] Lighting/time-of-day detection
- [ ] Graceful degradation: general description at low quality

**OCR Module:**
- [ ] Tesseract backend
- [ ] EasyOCR backend
- [ ] Region detection (where the text is)
- [ ] Language detection
- [ ] Graceful degradation: does NOT work at low quality (requires quality>0.6)

**Face Module:**
- [ ] Face detection (bounding boxes)
- [ ] Landmarks (eyes, nose, mouth)
- [ ] Embeddings (feature vectors)
- [ ] Recognition (comparison against the database)
- [ ] Registration of new people
- [ ] Emotions (optional)
- [ ] Graceful degradation: detection only at low quality

**Completion criteria:**
- Each module has min. 2 swappable backends
- Tests with real images
- Documentation: how to add a new backend

---

### Phase 4: Vision Cortex (integration)

**Goal:** Integrated visual perception as a single "sense".

**Structure:**
```
agent_core/vision/
├── cortex.py                # VisionCortex - the main integrator
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
- [ ] `VisionCortex` - coordinator of all components
- [ ] `AttentionMechanism` - where Maria "looks"
- [ ] `VisionModeManager` - automatic mode switching
- [ ] `VisionPercept` - unified output
- [ ] `VisionAlertSystem` - proactive notifications
- [ ] Adapter to Maria Consciousness (dual format)
- [ ] REPL command: `/vision` (status, preview, etc.)
- [ ] Web UI API: `/api/vision`

**Completion criteria:**
- Pipeline works end-to-end
- Maria can describe what she sees in natural language
- Graceful degradation at every level
- Integration with consciousness (Unified Perception)

---

## 11. Testing

### Unit tests

```python
def test_graceful_degradation():
    """A sensor with problems still returns partial data."""
    sensor = MockSensor(health=0.3, issues=[SensorIssue.HEAVY_NOISE])
    frame = sensor.capture_frame()

    assert frame is not None
    assert frame.quality < 0.5
    assert SensorIssue.HEAVY_NOISE in frame.degradations

def test_module_fallback():
    """The module switches to degraded mode at low quality."""
    module = FaceModule(backend=MockBackend())

    # Good quality - full analysis
    good_frame = ProcessedFrame(quality=0.9)
    result = module.analyze(good_frame)
    assert result.faces is not None

    # Low quality - detection only (no identification)
    bad_frame = ProcessedFrame(quality=0.3)
    result = module.analyze_degraded(bad_frame, [Degradation.HEAVY_NOISE])
    assert result.faces_detected >= 0
    assert all(f.identity is None for f in result.faces)
```

### Integration tests

```python
def test_full_perception_pipeline():
    """The full pipeline from sensor to VisionPercept."""
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

## 12. Future extensions

### Multi-camera fusion

```
- Multiple cameras -> a single coherent view
- Stereoscopy (depth)
- 360 degrees
```

### Learning

```
- Learning new faces
- Learning the normal state of the room
- Anomaly detection
```

### Integration with other senses

```
- Vision + Audio: recognizing who is speaking
- Vision + Motion sensors: verification
- Vision + Time: patterns (who comes at what time)
```

---

*This document defines the architecture. The detailed implementation of each module should be developed separately, taking the chosen AI backend into account.*
