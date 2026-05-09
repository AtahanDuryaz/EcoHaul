"""
Environment module — simülasyona gerçekçi kentsel atık dinamikleri katar.

Katmanlar (bağımlılık sırası):
  1. DistrictType     : ilçe/bölge sınıflandırması (enum)
  2. HourlyProfiles   : her district için saatlik dolum çarpanları (veri)
  3. NoiseModel       : ±%10 Gaussian gürültü (deterministik olmayan simülasyon)
  4. Event / Manager  : geçici yüksek-talep olayları (konser, maç, festival…)
  5. Public API       : assign_district(), effective_fill_rate()

Dışarıdan yalnızca bu ikisi çağrılır:
  - assign_district(region: str) -> DistrictType
  - effective_fill_rate(base_rate, district, hour, events) -> float
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum

# ══════════════════════════════════════════════════════════════════════════════
# KATMAN 1 — DistrictType
# ══════════════════════════════════════════════════════════════════════════════

class DistrictType(str, Enum):
    RESIDENTIAL = "residential"   # konut alanı — akşam piki
    OFFICE      = "office"        # iş merkezi — sabah/öğle piki
    MALL        = "mall"          # AVM — öğleden sonra/akşam piki
    UNIVERSITY  = "university"    # kampüs — ders saatleri piki
    TOURIST     = "tourist"       # turizm — öğle/akşam piki


# ══════════════════════════════════════════════════════════════════════════════
# KATMAN 2 — HourlyProfiles
# Saat 0-23 için dolum hızı çarpanı.  1.0 = ortalama, 2.0 = 2x hızlı.
# ══════════════════════════════════════════════════════════════════════════════

# Her district için 24 saatlik profil.  Değerler gerçekçi kentsel gözlemlere dayanır.
HOURLY_PROFILES: dict[DistrictType, list[float]] = {

    # Konut: gece sakin, sabah kahvaltı, akşam yoğun (aile evde)
    DistrictType.RESIDENTIAL: [
        0.2, 0.2, 0.2, 0.2, 0.2, 0.3,   # 00-05  gece
        0.6, 0.9, 0.8, 0.6, 0.5, 0.5,   # 06-11  sabah
        0.6, 0.6, 0.5, 0.6, 0.8, 1.2,   # 12-17  öğlen / dönüş
        1.8, 2.0, 1.7, 1.3, 0.8, 0.4,   # 18-23  akşam piki
    ],

    # Ofis: gece kapalı, sabah-öğle arası yoğun, akşam boş
    DistrictType.OFFICE: [
        0.1, 0.1, 0.1, 0.1, 0.1, 0.2,   # 00-05  kapalı
        0.4, 0.9, 1.8, 1.9, 1.7, 1.4,   # 06-11  sabah piki
        1.6, 1.5, 1.3, 1.1, 0.7, 0.3,   # 12-17  öğleden sonra düşüş
        0.2, 0.1, 0.1, 0.1, 0.1, 0.1,   # 18-23  gece
    ],

    # AVM: gece kapalı, öğleden sonra / akşam piki
    DistrictType.MALL: [
        0.1, 0.1, 0.1, 0.1, 0.1, 0.1,   # 00-05  kapalı
        0.1, 0.2, 0.4, 0.7, 1.0, 1.2,   # 06-11  açılış
        1.4, 1.6, 1.9, 2.1, 2.2, 2.3,   # 12-17  öğleden sonra piki
        2.4, 2.2, 1.6, 0.9, 0.3, 0.1,   # 18-23  akşam piki → kapanış
    ],

    # Üniversite: gece sakin, ders saatlerinde yoğun, akşam düşer
    DistrictType.UNIVERSITY: [
        0.1, 0.1, 0.1, 0.1, 0.1, 0.2,   # 00-05  gece
        0.3, 0.6, 1.4, 1.9, 1.8, 1.6,   # 06-11  sabah dersleri
        1.9, 1.8, 1.7, 1.5, 1.1, 0.6,   # 12-17  öğlen / öğleden sonra
        0.4, 0.3, 0.2, 0.2, 0.1, 0.1,   # 18-23  akşam
    ],

    # Turist: gece sakin, öğle → akşam çift pik (turistler + barlar)
    DistrictType.TOURIST: [
        0.3, 0.2, 0.2, 0.2, 0.2, 0.3,   # 00-05  gece hayatı sonu
        0.4, 0.5, 0.7, 1.0, 1.4, 1.7,   # 06-11  turist sabahı
        1.9, 2.0, 2.1, 2.0, 1.9, 1.8,   # 12-17  öğle piki
        1.9, 2.1, 2.0, 1.7, 1.2, 0.6,   # 18-23  akşam / bar saatleri
    ],
}


def hourly_multiplier(district: DistrictType, hour: int) -> float:
    """Belirtilen district ve saat için çarpanı döndür."""
    return HOURLY_PROFILES[district][hour % 24]


# ══════════════════════════════════════════════════════════════════════════════
# KATMAN 3 — NoiseModel
# Gaussian gürültü: her fill tick'te gerçek hayatın belirsizliğini simüle eder.
# ══════════════════════════════════════════════════════════════════════════════

_NOISE_STD = 0.10   # standart sapma: ±%10


def apply_noise(value: float) -> float:
    """Değere ±%10 Gaussian gürültü ekle; sonuç negatif olamaz."""
    noise_factor = 1.0 + random.gauss(0.0, _NOISE_STD)
    return max(0.0, value * noise_factor)


# ══════════════════════════════════════════════════════════════════════════════
# KATMAN 4 — Event System
# Geçici yüksek-talep olayları belirli district tiplerini etkiler.
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Event:
    """Tek bir geçici talep olayı."""
    event_id:            str
    event_type:          str               # "concert", "match", "festival"…
    start_sim_s:         float
    end_sim_s:           float
    affected_districts:  list[DistrictType]
    multiplier:          float             # dolum hızı çarpanı (örn. 2.5)
    description:         str = ""

    def is_active(self, sim_s: float) -> bool:
        return self.start_sim_s <= sim_s <= self.end_sim_s

    def affects(self, district: DistrictType) -> bool:
        return district in self.affected_districts


# Önceden tanımlı event şablonları:
# (event_type, etkilenen district'ler, çarpan aralığı, süre sim-saniye)
_EVENT_TEMPLATES: list[tuple] = [
    ("concert",  [DistrictType.TOURIST, DistrictType.RESIDENTIAL],
     (1.8, 3.0), 4 * 3_600),

    ("match",    [DistrictType.TOURIST, DistrictType.MALL],
     (2.0, 3.5), 3 * 3_600),

    ("festival", [DistrictType.TOURIST, DistrictType.MALL, DistrictType.RESIDENTIAL],
     (1.5, 2.5), 8 * 3_600),

    ("sale",     [DistrictType.MALL],
     (1.5, 2.0), 6 * 3_600),

    ("weekend",  list(DistrictType),
     (1.2, 1.6), 48 * 3_600),
]

# Eventler arası minimum ve maksimum bekleme süresi (sim-saniye)
_EVENT_MIN_GAP_S = 12 * 3_600
_EVENT_MAX_GAP_S = 48 * 3_600


class EventManager:
    """
    Aktif olayları üretir, takip eder ve temizler.

    Kullanım:
      manager.tick(sim_s)          → her tick'te çağır; yeni event üretebilir
      manager.active(sim_s)        → o an aktif Event listesi
      manager.reset()              → simülasyon sıfırlandığında
    """

    def __init__(self) -> None:
        self._events: list[Event] = []
        self._counter: int = 0
        self._next_spawn_s: float = _EVENT_MIN_GAP_S

    # ── Public API ──────────────────────────────────────────────────────────

    def tick(self, sim_s: float) -> Event | None:
        """
        Zamanı ilerlet; yeni event oluşturulursa döndür, yoksa None.
        Süresi dolmuş eski eventleri de temizler.
        """
        self._cleanup(sim_s)
        if sim_s >= self._next_spawn_s:
            return self._spawn(sim_s)
        return None

    def active(self, sim_s: float) -> list[Event]:
        """O an aktif olan tüm eventleri döndür."""
        return [e for e in self._events if e.is_active(sim_s)]

    def reset(self) -> None:
        self._events.clear()
        self._counter = 0
        self._next_spawn_s = _EVENT_MIN_GAP_S

    # ── Internal ────────────────────────────────────────────────────────────

    def _spawn(self, sim_s: float) -> Event:
        """Rastgele bir şablondan event oluştur ve listeye ekle."""
        self._counter += 1
        etype, districts, mult_range, duration = random.choice(_EVENT_TEMPLATES)
        mult = round(random.uniform(*mult_range), 2)

        ev = Event(
            event_id           = f"EVT_{self._counter:04d}",
            event_type         = etype,
            start_sim_s        = sim_s,
            end_sim_s          = sim_s + duration,
            affected_districts = list(districts),
            multiplier         = mult,
            description        = f"{etype} (x{mult})",
        )
        self._events.append(ev)
        # Sonraki spawn zamanını belirle
        self._next_spawn_s = sim_s + random.uniform(_EVENT_MIN_GAP_S, _EVENT_MAX_GAP_S)
        return ev

    def _cleanup(self, sim_s: float) -> None:
        """Süresi dolmuş eventleri kaldır (bellek kontrolü)."""
        self._events = [e for e in self._events if e.end_sim_s >= sim_s]


# ══════════════════════════════════════════════════════════════════════════════
# KATMAN 5 — Public API
# ══════════════════════════════════════════════════════════════════════════════

# Dublin için gerçekçi district dağılımı
_DISTRICT_DISTRIBUTION: list[tuple[DistrictType, float]] = [
    (DistrictType.RESIDENTIAL, 0.40),
    (DistrictType.OFFICE,      0.20),
    (DistrictType.MALL,        0.15),
    (DistrictType.UNIVERSITY,  0.15),
    (DistrictType.TOURIST,     0.10),
]

# Region string → district tipi için anahtar kelimeler
_REGION_KEYWORDS: dict[DistrictType, list[str]] = {
    DistrictType.UNIVERSITY: ["univ", "college", "campus", "tech"],
    DistrictType.MALL:       ["mall", "shop", "centre", "center", "retail"],
    DistrictType.TOURIST:    ["hotel", "tourist", "museum", "temple", "temple bar"],
    DistrictType.OFFICE:     ["office", "business", "corp", "dock", "ifsc"],
}


def assign_district(region: str | None = None) -> DistrictType:
    """
    Bin'in region string'inden district tipini çıkar.
    Tanınmayan region için Dublin dağılımından rastgele ata.
    """
    if region:
        r = region.lower()
        for district, keywords in _REGION_KEYWORDS.items():
            if any(kw in r for kw in keywords):
                return district

    # Ağırlıklı rastgele seçim
    rand = random.random()
    cumulative = 0.0
    for district, prob in _DISTRICT_DISTRIBUTION:
        cumulative += prob
        if rand <= cumulative:
            return district
    return DistrictType.RESIDENTIAL


def effective_fill_rate(
    base_rate: float,
    district:  DistrictType,
    hour:      int,
    events:    list[Event],
) -> float:
    """
    Bir bin'in bu tick'teki gerçek dolum hızını hesapla.

    Formül:
      rate = base_rate × hourly_multiplier × event_multiplier × noise

    Args:
      base_rate : bin'in sabit temel hızı (%/sim-saat)
      district  : bin'in district tipi
      hour      : sanal saatin saati (0-23)
      events    : o an aktif Event listesi
    """
    h_mult = hourly_multiplier(district, hour)

    # Aynı anda birden fazla event olabilir — en yüksek çarpanı al
    e_mult = 1.0
    for ev in events:
        if ev.affects(district):
            e_mult = max(e_mult, ev.multiplier)

    rate = base_rate * h_mult * e_mult
    return apply_noise(rate)
