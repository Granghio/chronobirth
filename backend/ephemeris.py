"""
Calcoli astrologici per ChronoBirth.

Prova a usare Swiss Ephemeris (pyswisseph) se installato.
Su Windows spesso pyswisseph fallisce senza Visual C++ Build Tools:
in quel caso usa un motore pure-Python (stesso tipo di formule del browser).

Il JSON di risposta resta allineato al frontend.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# ---------------------------------------------------------------------------
# Swiss Ephemeris opzionale
# ---------------------------------------------------------------------------
try:
    import swisseph as swe  # type: ignore

    HAS_SWISS = True
    ENGINE_NAME = "Swiss Ephemeris"
    ENGINE_VERSION = str(getattr(swe, "version", "unknown"))
except Exception:  # noqa: BLE001
    swe = None  # type: ignore
    HAS_SWISS = False
    ENGINE_NAME = "Python ephemeris (fallback)"
    ENGINE_VERSION = "builtin-1.0"

# Segni in italiano (stesso ordine del frontend)
SIGNS_IT = [
    "Ariete",
    "Toro",
    "Gemelli",
    "Cancro",
    "Leone",
    "Vergine",
    "Bilancia",
    "Scorpione",
    "Sagittario",
    "Capricorno",
    "Acquario",
    "Pesci",
]

ASPECTS = [
    {"name": "congiunzione", "angle": 0, "orb": 7, "score": 6},
    {"name": "sestile", "angle": 60, "orb": 4, "score": 3},
    {"name": "quadratura", "angle": 90, "orb": 5, "score": 5},
    {"name": "trigono", "angle": 120, "orb": 5, "score": 4},
    {"name": "opposizione", "angle": 180, "orb": 6, "score": 6},
]

HOUSE_SYSTEMS = {
    "P": b"P",
    "K": b"K",
    "O": b"O",
    "R": b"R",
    "C": b"C",
    "E": b"E",
    "W": b"W",
    "A": b"A",
}

# Nomi pianeti usati dal frontend
PLANET_NAMES = [
    "Sole",
    "Luna",
    "Mercurio",
    "Venere",
    "Marte",
    "Giove",
    "Saturno",
    "Urano",
    "Nettuno",
    "Plutone",
    "Nodo Nord",
]


def normalize_deg(d: float) -> float:
    return d % 360.0


def normalize_180(d: float) -> float:
    x = normalize_deg(d)
    return x - 360.0 if x > 180.0 else x


def rad(d: float) -> float:
    return d * math.pi / 180.0


def deg(r: float) -> float:
    return r * 180.0 / math.pi


def zodiac_from_longitude(lon: float) -> dict[str, Any]:
    lon = normalize_deg(lon)
    sign_idx = int(lon // 30) % 12
    degree_f = lon % 30
    degree = int(degree_f)
    minute = int((degree_f - degree) * 60)
    sign = SIGNS_IT[sign_idx]
    return {
        "sign": sign,
        "degree": degree,
        "minute": minute,
        "text": f"{degree}°{minute:02d}′ {sign}",
        "longitude": lon,
    }


def format_planet(
    name: str,
    lon: float,
    speed: float | None = None,
    *,
    swiss: bool | None = None,
) -> dict[str, Any]:
    z = zodiac_from_longitude(lon)
    if swiss is None:
        swiss = HAS_SWISS
    retro = bool(
        speed is not None
        and speed < 0
        and name not in ("Sole", "Luna", "Ascendente", "Medio Cielo")
    )
    return {
        "body": name,
        "longitude": z["longitude"],
        "sign": z["sign"],
        "degree": z["degree"],
        "minute": z["minute"],
        "text": z["text"],
        "retrograde": retro,
        "speed": speed,
        "swiss": bool(swiss),
    }


def local_to_utc(date_str: str, time_str: str, tz_name: str) -> datetime:
    time_str = time_str or "12:00"
    if len(time_str) == 5:
        time_str = time_str + ":00"
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Timezone non valida: {tz_name}") from exc
    local_naive = datetime.fromisoformat(f"{date_str}T{time_str}")
    return local_naive.replace(tzinfo=tz).astimezone(timezone.utc)


def datetime_to_jd_ut(dt_utc: datetime) -> float:
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    else:
        dt_utc = dt_utc.astimezone(timezone.utc)
    hour = (
        dt_utc.hour
        + dt_utc.minute / 60.0
        + dt_utc.second / 3600.0
        + dt_utc.microsecond / 3_600_000_000.0
    )
    if HAS_SWISS:
        return float(swe.julday(dt_utc.year, dt_utc.month, dt_utc.day, hour, swe.GREG_CAL))
    # JD standard (UTC)
    y, m, d = dt_utc.year, dt_utc.month, dt_utc.day
    if m <= 2:
        y -= 1
        m += 12
    A = y // 100
    B = 2 - A + A // 4
    jd0 = int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + B - 1524.5
    return jd0 + hour / 24.0


# ===========================================================================
# Motore Swiss Ephemeris
# ===========================================================================
def _swiss_bodies() -> list[tuple[str, int]]:
    return [
        ("Sole", swe.SUN),
        ("Luna", swe.MOON),
        ("Mercurio", swe.MERCURY),
        ("Venere", swe.VENUS),
        ("Marte", swe.MARS),
        ("Giove", swe.JUPITER),
        ("Saturno", swe.SATURN),
        ("Urano", swe.URANUS),
        ("Nettuno", swe.NEPTUNE),
        ("Plutone", swe.PLUTO),
        ("Nodo Nord", swe.TRUE_NODE),
    ]


def _swiss_calc_body(jd_ut: float, body_id: int) -> tuple[float, float]:
    flags = swe.FLG_SWIEPH | swe.FLG_SPEED
    try:
        result, _ = swe.calc_ut(jd_ut, body_id, flags)
    except Exception:
        result, _ = swe.calc_ut(jd_ut, body_id, swe.FLG_MOSEPH | swe.FLG_SPEED)
    lon = float(result[0])
    speed = float(result[3]) if len(result) > 3 else 0.0
    return normalize_deg(lon), speed


def _swiss_planets(jd_ut: float) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, body_id in _swiss_bodies():
        lon, speed = _swiss_calc_body(jd_ut, body_id)
        out[name] = format_planet(name, lon, speed, swiss=True)
    return out


def _swiss_houses(
    jd_ut: float, lat: float, lon: float, house_system: str = "P"
) -> tuple[dict[str, dict[str, Any]], list[float]]:
    hs = HOUSE_SYSTEMS.get((house_system or "P").upper(), b"P")
    try:
        cusps, ascmc = swe.houses(jd_ut, lat, lon, hs)
    except Exception:
        cusps, ascmc = swe.houses(jd_ut, lat, lon, b"E")
    points = {
        "Ascendente": format_planet("Ascendente", float(ascmc[0]), None, swiss=True),
        "Medio Cielo": format_planet("Medio Cielo", float(ascmc[1]), None, swiss=True),
    }
    house_list: list[float] = []
    for i in range(1, 13):
        house_list.append(normalize_deg(float(cusps[i])) if i < len(cusps) else 0.0)
    return points, house_list


# ===========================================================================
# Motore pure-Python (no compilatori, funziona su Windows)
# Formule orbitali semplificate (stesso approccio del fallback browser)
# ===========================================================================
def _days_since_j2000(jd: float) -> float:
    return jd - 2451543.5


def _kepler(Mdeg: float, e: float) -> float:
    M = rad(normalize_deg(Mdeg))
    E = M + e * math.sin(M) * (1 + e * math.cos(M))
    for _ in range(10):
        E = E - (E - e * math.sin(E) - M) / (1 - e * math.cos(E))
    return E


def _orbital_elements(body: str, d: float) -> dict[str, float]:
    # Elementi approssimati (radianzi/gradi come nel frontend JS)
    table = {
        "Mercury": {
            "N": 48.3313 + 3.24587e-5 * d,
            "i": 7.0047 + 5.00e-8 * d,
            "w": 29.1241 + 1.01444e-5 * d,
            "a": 0.387098,
            "e": 0.205635 + 5.59e-10 * d,
            "M": 168.6562 + 4.0923344368 * d,
        },
        "Venus": {
            "N": 76.6799 + 2.46590e-5 * d,
            "i": 3.3946 + 2.75e-8 * d,
            "w": 54.8910 + 1.38374e-5 * d,
            "a": 0.723330,
            "e": 0.006773 - 1.302e-9 * d,
            "M": 48.0052 + 1.6021302244 * d,
        },
        "Earth": {
            "N": 0.0,
            "i": 0.0,
            "w": 282.9404 + 4.70935e-5 * d,
            "a": 1.0,
            "e": 0.016709 - 1.151e-9 * d,
            "M": 356.0470 + 0.9856002585 * d,
        },
        "Mars": {
            "N": 49.5574 + 2.11081e-5 * d,
            "i": 1.8497 - 1.78e-8 * d,
            "w": 286.5016 + 2.92961e-5 * d,
            "a": 1.523688,
            "e": 0.093405 + 2.516e-9 * d,
            "M": 18.6021 + 0.5240207766 * d,
        },
        "Jupiter": {
            "N": 100.4542 + 2.76854e-5 * d,
            "i": 1.3030 - 1.557e-7 * d,
            "w": 273.8777 + 1.64505e-5 * d,
            "a": 5.20256,
            "e": 0.048498 + 4.469e-9 * d,
            "M": 19.8950 + 0.0830853001 * d,
        },
        "Saturn": {
            "N": 113.6634 + 2.38980e-5 * d,
            "i": 2.4886 - 1.081e-7 * d,
            "w": 339.3939 + 2.97661e-5 * d,
            "a": 9.55475,
            "e": 0.055546 - 9.499e-9 * d,
            "M": 316.9670 + 0.0334442282 * d,
        },
        "Uranus": {
            "N": 74.0005 + 1.3978e-5 * d,
            "i": 0.7733 + 1.9e-8 * d,
            "w": 96.6612 + 3.0565e-5 * d,
            "a": 19.18171 - 1.55e-8 * d,
            "e": 0.047318 + 7.45e-9 * d,
            "M": 142.5905 + 0.011725806 * d,
        },
        "Neptune": {
            "N": 131.7806 + 3.0173e-5 * d,
            "i": 1.7700 - 2.55e-7 * d,
            "w": 272.8461 - 6.027e-6 * d,
            "a": 30.05826 + 3.313e-8 * d,
            "e": 0.008606 + 2.15e-9 * d,
            "M": 260.2471 + 0.005995147 * d,
        },
        "Pluto": {
            "N": 110.30347,
            "i": 17.14175,
            "w": 113.76329,
            "a": 39.48168677,
            "e": 0.24880766,
            "M": 14.53 + 0.0039757 * d,
        },
    }
    return table[body]


def _heliocentric(body: str, d: float) -> dict[str, float]:
    el = _orbital_elements(body, d)
    E = _kepler(el["M"], el["e"])
    xv = el["a"] * (math.cos(E) - el["e"])
    yv = el["a"] * (math.sqrt(1 - el["e"] * el["e"]) * math.sin(E))
    v = deg(math.atan2(yv, xv))
    r = math.sqrt(xv * xv + yv * yv)
    N, i, vw = rad(el["N"]), rad(el["i"]), rad(v + el["w"])
    xh = r * (math.cos(N) * math.cos(vw) - math.sin(N) * math.sin(vw) * math.cos(i))
    yh = r * (math.sin(N) * math.cos(vw) + math.cos(N) * math.sin(vw) * math.cos(i))
    zh = r * (math.sin(vw) * math.sin(i))
    return {"x": xh, "y": yh, "z": zh, "r": r, "lon": normalize_deg(deg(math.atan2(yh, xh)))}


def _moon_longitude(jd: float) -> float:
    d = _days_since_j2000(jd)
    N = 125.1228 - 0.0529538083 * d
    i = 5.1454
    w = 318.0634 + 0.1643573223 * d
    a = 60.2666
    e = 0.054900
    M = 115.3654 + 13.0649929509 * d
    E = _kepler(M, e)
    xv = a * (math.cos(E) - e)
    yv = a * (math.sqrt(1 - e * e) * math.sin(E))
    v = deg(math.atan2(yv, xv))
    r = math.sqrt(xv * xv + yv * yv)
    xh = r * (
        math.cos(rad(N)) * math.cos(rad(v + w))
        - math.sin(rad(N)) * math.sin(rad(v + w)) * math.cos(rad(i))
    )
    yh = r * (
        math.sin(rad(N)) * math.cos(rad(v + w))
        + math.cos(rad(N)) * math.sin(rad(v + w)) * math.cos(rad(i))
    )
    lon = normalize_deg(deg(math.atan2(yh, xh)))
    Ms = normalize_deg(356.0470 + 0.9856002585 * d)
    Mm = normalize_deg(M)
    D = normalize_deg(lon - (normalize_deg(282.9404 + 4.70935e-5 * d + Ms)))
    F = normalize_deg(lon - N)
    lon += -1.274 * math.sin(rad(Mm - 2 * D)) + 0.658 * math.sin(rad(2 * D)) - 0.186 * math.sin(rad(Ms))
    lon += -0.059 * math.sin(rad(2 * Mm - 2 * D)) - 0.057 * math.sin(rad(Mm - 2 * D + Ms))
    lon += 0.053 * math.sin(rad(Mm + 2 * D)) + 0.046 * math.sin(rad(2 * D - Ms))
    lon += 0.041 * math.sin(rad(Mm - Ms)) - 0.031 * math.sin(rad(Mm + Ms))
    lon += -0.015 * math.sin(rad(2 * F - 2 * D)) + 0.011 * math.sin(rad(Mm - 4 * D))
    return normalize_deg(lon)


def _planet_longitude(name: str, jd: float) -> float:
    if name == "Luna":
        return _moon_longitude(jd)
    d = _days_since_j2000(jd)
    earth = _heliocentric("Earth", d)
    # Con elementi orbitali tipo Schlyter (come nel frontend JS),
    # earth["lon"] coincide già con la longitudine geocentrica del Sole.
    if name == "Sole":
        return normalize_deg(earth["lon"])
    if name == "Nodo Nord":
        return normalize_deg(125.1228 - 0.0529538083 * d)
    key = {
        "Mercurio": "Mercury",
        "Venere": "Venus",
        "Marte": "Mars",
        "Giove": "Jupiter",
        "Saturno": "Saturn",
        "Urano": "Uranus",
        "Nettuno": "Neptune",
        "Plutone": "Pluto",
    }.get(name)
    if not key:
        return 0.0
    p = _heliocentric(key, d)
    # geocentrico approssimato
    return normalize_deg(deg(math.atan2(p["y"] + earth["y"], p["x"] + earth["x"])))


def _is_retrograde(name: str, jd: float) -> bool:
    if name in ("Sole", "Luna", "Ascendente", "Medio Cielo"):
        return False
    d1 = _planet_longitude(name, jd - 1.0)
    d2 = _planet_longitude(name, jd + 1.0)
    delta = (normalize_deg(d2) - normalize_deg(d1) + 540) % 360 - 180
    return delta < 0


def _py_planets(jd_ut: float) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name in PLANET_NAMES:
        lon = _planet_longitude(name, jd_ut)
        lon2 = _planet_longitude(name, jd_ut + 1.0 / 24.0)
        speed = normalize_180(lon2 - lon) * 24.0  # °/giorno approx
        if name not in ("Sole", "Luna") and _is_retrograde(name, jd_ut):
            speed = -abs(speed)
        out[name] = format_planet(name, lon, speed, swiss=False)
    return out


def _gmst_deg(jd: float) -> float:
    T = (jd - 2451545.0) / 36525.0
    return normalize_deg(
        280.46061837
        + 360.98564736629 * (jd - 2451545.0)
        + 0.000387933 * T * T
        - T * T * T / 38710000.0
    )


def _ascendant_longitude(jd: float, latitude: float, longitude: float) -> float:
    """Ascendente per ricerca radici (come nel frontend)."""
    lst = normalize_deg(_gmst_deg(jd) + longitude)
    T = (jd - 2451545.0) / 36525.0
    eps = 23.439291 - 0.0130042 * T
    phi = rad(latitude)

    def altitude(lambda_deg: float) -> float:
        l = rad(lambda_deg)
        e = rad(eps)
        ra = normalize_deg(deg(math.atan2(math.sin(l) * math.cos(e), math.cos(l))))
        dec = deg(math.asin(math.sin(e) * math.sin(l)))
        H = rad(normalize_180(lst - ra))
        de = rad(dec)
        return math.asin(math.sin(phi) * math.sin(de) + math.cos(phi) * math.cos(de) * math.cos(H))

    roots: list[float] = []
    prev_l, prev = 0.0, altitude(0.0)
    for l in range(1, 361):
        cur = altitude(float(l))
        if prev == 0 or cur == 0 or prev * cur < 0:
            a, b, fa = prev_l, float(l), prev
            for _ in range(40):
                mid = (a + b) / 2
                fm = altitude(mid)
                if fa * fm <= 0:
                    b = mid
                else:
                    a = mid
                    fa = fm
            roots.append(normalize_deg((a + b) / 2))
        prev_l, prev = float(l), cur

    for root in roots:
        l = rad(root)
        e = rad(eps)
        ra = normalize_deg(deg(math.atan2(math.sin(l) * math.cos(e), math.cos(l))))
        H = normalize_180(lst - ra)
        if H < 0:
            return root
    return roots[0] if roots else 0.0


def _midheaven_longitude(jd: float, longitude: float) -> float:
    """MC ≈ RAMC trasformato in longitudine eclittica (approssimato)."""
    lst = normalize_deg(_gmst_deg(jd) + longitude)
    T = (jd - 2451545.0) / 36525.0
    eps = rad(23.439291 - 0.0130042 * T)
    # da RA=lst, Dec=0 sull'equatore celeste → eclittica
    ra = rad(lst)
    # lon eclittica da RA con Dec=0: tan(lon)=sin(RA)/cos(RA)*cos(eps) ... formula standard
    lon = deg(math.atan2(math.sin(ra) * math.cos(eps), math.cos(ra)))
    return normalize_deg(lon)


def _py_houses(
    jd_ut: float, lat: float, lon: float, house_system: str = "P"
) -> tuple[dict[str, dict[str, Any]], list[float]]:
    asc = _ascendant_longitude(jd_ut, lat, lon)
    mc = _midheaven_longitude(jd_ut, lon)
    points = {
        "Ascendente": format_planet("Ascendente", asc, None, swiss=False),
        "Medio Cielo": format_planet("Medio Cielo", mc, None, swiss=False),
    }
    # Case equal dall'ascendente (semplice e stabile; Placidus puro richiederebbe più math)
    # Se house_system W: whole sign
    hs = (house_system or "P").upper()
    house_list: list[float] = []
    if hs == "W":
        start = int(asc // 30) * 30.0
        for i in range(12):
            house_list.append(normalize_deg(start + i * 30.0))
    else:
        for i in range(12):
            house_list.append(normalize_deg(asc + i * 30.0))
    return points, house_list


# ===========================================================================
# API comune
# ===========================================================================
def calc_planets(jd_ut: float) -> dict[str, dict[str, Any]]:
    if HAS_SWISS:
        return _swiss_planets(jd_ut)
    return _py_planets(jd_ut)


def calc_houses(
    jd_ut: float, lat: float, lon: float, house_system: str = "P"
) -> tuple[dict[str, dict[str, Any]], list[float]]:
    if HAS_SWISS:
        return _swiss_houses(jd_ut, lat, lon, house_system)
    return _py_houses(jd_ut, lat, lon, house_system)


def aspect_between(lon_a: float | None, lon_b: float | None) -> dict[str, Any] | None:
    if lon_a is None or lon_b is None:
        return None
    diff = abs(normalize_180(lon_b - lon_a))
    best = None
    for a in ASPECTS:
        orb = abs(diff - a["angle"])
        if orb <= a["orb"] and (best is None or orb < best["orb"]):
            best = {**a, "orb": orb}
    return best


def find_major_transits(
    natal_planets: dict[str, dict[str, Any]],
    transit_planets: dict[str, dict[str, Any]],
    limit: int = 8,
) -> list[dict[str, Any]]:
    targets = ["Sole", "Luna", "Ascendente", "Mercurio", "Venere", "Marte", "Medio Cielo"]
    movers = ["Luna", "Sole", "Mercurio", "Venere", "Marte", "Giove", "Saturno"]
    found: list[dict[str, Any]] = []
    for t in movers:
        for n in targets:
            if t not in transit_planets or n not in natal_planets:
                continue
            lon_t = transit_planets[t].get("longitude")
            lon_n = natal_planets[n].get("longitude")
            asp = aspect_between(lon_t, lon_n)
            if not asp:
                continue
            score = asp["score"] + (0 if t == "Luna" else 1 if t == "Sole" else 2)
            found.append(
                {
                    "transit": t,
                    "natal": n,
                    "aspect": asp["name"],
                    "orb": round(float(asp["orb"]), 2),
                    "score": score,
                    "text": asp["name"],
                }
            )
    found.sort(key=lambda x: (-x["score"], x["orb"]))
    return found[:limit]


@dataclass
class NatalInput:
    name: str
    date: str
    time: str
    place: str
    lat: float
    lon: float
    timezone: str
    house_system: str = "P"


def engine_info() -> dict[str, Any]:
    return {
        "engine": ENGINE_NAME,
        "engine_version": ENGINE_VERSION,
        "has_swiss": HAS_SWISS,
    }


def compute_natal(data: NatalInput) -> dict[str, Any]:
    utc = local_to_utc(data.date, data.time, data.timezone)
    jd = datetime_to_jd_ut(utc)

    planets = calc_planets(jd)
    house_points, cusps = calc_houses(jd, data.lat, data.lon, data.house_system)
    planets.update(house_points)

    now_utc = datetime.now(timezone.utc)
    jd_now = datetime_to_jd_ut(now_utc)
    sky = calc_planets(jd_now)
    transits = find_major_transits(planets, sky)

    return {
        "name": data.name,
        "place": data.place,
        "lat": data.lat,
        "lon": data.lon,
        "timezone": data.timezone,
        "local_datetime": f"{data.date}T{(data.time or '12:00')[:5]}",
        "utc_datetime": utc.isoformat().replace("+00:00", "Z"),
        "julian_day": jd,
        "house_system": (data.house_system or "P").upper(),
        "engine": ENGINE_NAME,
        "engine_version": ENGINE_VERSION,
        "has_swiss": HAS_SWISS,
        "natal": {
            "planets": planets,
            "houses": cusps,
        },
        "current_sky": {
            "utc_datetime": now_utc.isoformat().replace("+00:00", "Z"),
            "planets": sky,
        },
        "transits": transits,
    }
