"""REPL commands: /vision - visual perception pipeline."""

import logging
from datetime import datetime

from agent_core.registry import MariaModule, CommandInfo

logger = logging.getLogger(__name__)


class VisionModule(MariaModule):
    """Vision subsystem REPL interface."""

    name = "vision"
    description = "Visual perception pipeline (oko)"

    def init(self, ctx) -> bool:
        self.ctx = ctx
        return True

    def get_commands(self):
        return [
            CommandInfo(
                "/vision", self._cmd_vision,
                "  /vision               - status wzroku (sensor, health, modules)\n"
                "  /vision snap          - zrob zdjecie i opisz co widze\n"
                "  /vision health        - szczegoly zdrowia sensora\n"
                "  /vision motion        - ostatni wynik detekcji ruchu\n"
                "  /vision scene         - ostatni opis sceny\n"
                "  /vision open          - otworz sensor\n"
                "  /vision close         - zamknij sensor",
                "[EYE] VISION (percepcja wizualna)",
            ),
        ]

    def _get_cortex(self):
        return getattr(self.ctx, "vision_cortex", None)

    def _cmd_vision(self, args):
        sub = args[0] if args else ""

        if sub == "snap":
            self._snap()
        elif sub == "health":
            self._show_health()
        elif sub == "motion":
            self._show_motion()
        elif sub == "scene":
            self._show_scene()
        elif sub == "open":
            self._open_sensor()
        elif sub == "close":
            self._close_sensor()
        else:
            self._show_status()

    def _show_status(self):
        cortex = self._get_cortex()
        if cortex is None:
            print("[Vision] Nie zainicjalizowano (brak VisionCortex)")
            return

        status = cortex.get_status()
        print(f"\n{'=' * 50}")
        print("  OKO - STATUS WZROKU")
        print(f"{'=' * 50}")
        print(f"  Sensory:        {status.get('sensor_count', 0)}")
        print(f"  Aktywny sensor: {status.get('active_sensor', 'brak')}")
        print(f"  Moduly:         {', '.join(status.get('active_modules', [])) or 'brak'}")

        health = status.get('sensor_health')
        if health is not None:
            print(f"  Zdrowie:        {health:.1%}")
        else:
            print("  Zdrowie:        --")

        quality = status.get('last_quality')
        if quality is not None:
            print(f"  Ostatnia jakosc: {quality:.1%}")

        last = cortex.last_percept
        if last:
            ts = datetime.fromtimestamp(last.timestamp).strftime("%H:%M:%S")
            print(f"  Ostatni obraz:  {ts}")
            print(f"  Podsumowanie:   {last.summary}")
        else:
            print("  Ostatni obraz:  brak")
        print(f"{'=' * 50}\n")

    def _snap(self):
        """Take a snapshot and show perception results (with LLaVA if available)."""
        cortex = self._get_cortex()
        if cortex is None:
            print("[Vision] Nie zainicjalizowano")
            return

        # Temporarily enable LLaVA for detailed scene description
        scene_mod = cortex._modules.get("scene")
        llava_fn = getattr(scene_mod, '_llava_describe', None) if scene_mod else None
        if scene_mod and llava_fn:
            scene_mod.set_llava_fn(llava_fn)
            print("[Vision] Robie zdjecie (z LLaVA - moze potrwac ~30s)...")
        else:
            print("[Vision] Robie zdjecie...")

        try:
            percept = cortex.perceive()
        except Exception as e:
            print(f"[Vision] Blad: {e}")
            return
        finally:
            # Disable LLaVA after snap to not block tick loop
            if scene_mod and llava_fn:
                scene_mod._llava_fn = None

        if percept is None:
            print("[Vision] Nie udalo sie zrobic zdjecia (brak sensora lub problem sprzetu)")
            return

        ts = datetime.fromtimestamp(percept.timestamp).strftime("%H:%M:%S")
        print(f"\n{'=' * 50}")
        print(f"  OBRAZ [{ts}]")
        print(f"{'=' * 50}")
        print(f"  Jakosc:      {percept.quality:.1%}")
        print(f"  Zdrowie:     {percept.vision_health.overall:.1%}")
        print(f"  Degradacja:  {percept.vision_health.degradation_level.value}")
        print(f"  Moduly:      {', '.join(percept.modules_run)}")
        print(f"  Czas:        {percept.total_processing_time_ms:.0f}ms")
        print(f"  Podsumowanie: {percept.summary}")

        if percept.motion:
            m = percept.motion
            print(f"\n  Ruch:         {'TAK' if m.motion_detected else 'NIE'}")
            if m.motion_detected:
                print(f"  Poziom:       {m.motion_level:.1%}")
                print(f"  Klasyfikacja: {m.classification.value}")
                print(f"  Alert:        {m.alert_level.value}")

        if percept.scene:
            s = percept.scene
            print(f"\n  Scena:        {s.description}")
            print(f"  Oswietlenie:  {s.lighting}")
            print(f"  Kolory:       {', '.join(s.dominant_colors)}")
            print(f"  Zlozonosc:    {s.complexity:.1%}")
            print(f"  Backend:      {s.backend_used}")

        print(f"{'=' * 50}\n")

    def _show_health(self):
        cortex = self._get_cortex()
        if cortex is None:
            print("[Vision] Nie zainicjalizowano")
            return

        sensor = cortex.active_sensor
        if sensor is None:
            print("[Vision] Brak aktywnego sensora")
            return

        h = sensor.health
        print(f"\n{'=' * 50}")
        print("  ZDROWIE SENSORA")
        print(f"{'=' * 50}")
        print(f"  Sensor:       {sensor.sensor_id}")
        print(f"  Ogolne:       {h.overall:.1%} ({h.degradation_level.value})")
        print(f"  Polaczenie:   {h.connection:.1%}")
        print(f"  Stream:       {h.stream:.1%}")
        print(f"  Rozdzielczosc: {h.resolution:.1%}")
        print(f"  Kolor:        {h.color:.1%}")
        print(f"  Ostrosc:      {h.focus:.1%}")
        print(f"  Ekspozycja:   {h.exposure:.1%}")
        print(f"  Szum:         {h.noise:.1%}")
        print(f"  Latencja:     {h.latency_ms:.0f}ms")
        if h.issues:
            issues_str = ", ".join(i.value for i in h.issues)
            print(f"  Problemy:     {issues_str}")
        print(f"\n  {h.to_human_description()}")
        print(f"{'=' * 50}\n")

    def _show_motion(self):
        cortex = self._get_cortex()
        if cortex is None:
            print("[Vision] Nie zainicjalizowano")
            return

        last = cortex.last_percept
        if last is None or last.motion is None:
            print("[Vision] Brak danych o ruchu. Uzyj /vision snap")
            return

        m = last.motion
        print(f"\n  Ruch:         {'WYKRYTO' if m.motion_detected else 'BRAK'}")
        if m.motion_detected:
            print(f"  Poziom:       {m.motion_level:.1%}")
            print(f"  Klasyfikacja: {m.classification.value}")
            print(f"  Alert:        {m.alert_level.value}")
            print(f"  Regiony:      {len(m.regions)}")

    def _show_scene(self):
        cortex = self._get_cortex()
        if cortex is None:
            print("[Vision] Nie zainicjalizowano")
            return

        last = cortex.last_percept
        if last is None or last.scene is None:
            print("[Vision] Brak opisu sceny. Uzyj /vision snap")
            return

        s = last.scene
        print(f"\n  Opis:         {s.description}")
        print(f"  Oswietlenie:  {s.lighting}")
        print(f"  Kolory:       {', '.join(s.dominant_colors)}")
        print(f"  Zlozonosc:    {s.complexity:.1%}")
        print(f"  Backend:      {s.backend_used}")

    def _open_sensor(self):
        cortex = self._get_cortex()
        if cortex is None:
            print("[Vision] Nie zainicjalizowano")
            return

        count = cortex.open_all_sensors()
        print(f"[Vision] Otwarto {count} sensor(ow)")

    def _close_sensor(self):
        cortex = self._get_cortex()
        if cortex is None:
            print("[Vision] Nie zainicjalizowano")
            return

        cortex.close_all_sensors()
        print("[Vision] Sensory zamkniete")
