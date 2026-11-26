"""Identify explicitly reported viewing angles in sighting passages."""
import re

VALUE = r"(?<![\d.−-])(?P<n>[+−-]?\d{1,3}(?:\.\d+)?)(?!\d|\.\d)"
UNIT = r"\s*(?:°|deg(?:ree)?s?\b)"
AZ = re.compile(r"\b(?:azimuth|bearing)\s*(?:of\s+|was\s+|[:=]\s*)?" + VALUE, re.I)
EL = re.compile(r"\b(?:elevation(?:\s+angle)?|angle\s+of\s+elevation)\s*(?:of\s+|was\s+|[:=]\s*)?" + VALUE + UNIT, re.I)
HORIZON = re.compile(VALUE + UNIT + r"\s+(?P<side>above|below)\s+(?:the\s+)?horizon\b", re.I)
COMPASS = dict(north=0, northeast=45, east=90, southeast=135, south=180, southwest=225, west=270, northwest=315)
DIRECTION = re.compile(r"\b(?:looking|facing|looked|in\s+the|to\s+the)\s+(?:towards?\s+)?(north(?:east|west)?|south(?:east|west)?|east|west)\b", re.I)
SIGHT = re.compile(r"\b(?:saw|sighting|observed|witness(?:ed)?|object|light[s]?|ufo|uap|orb)\b", re.I)


def reported_angles(text):
    if not SIGHT.search(text):
        return []
    rows = []
    for sentence in re.split(r"(?<=[.!?])\s+|[;\n]", text):
        if not SIGHT.search(sentence):
            continue
        azimuths, elevations = [], []
        for pattern, values, lower, upper in [(AZ, azimuths, 0, 360), (EL, elevations, -90, 90), (HORIZON, elevations, 0, 90)]:
            for match in pattern.finditer(sentence):
                value = float(match['n'].replace('−', '-'))
                if lower <= value <= upper:
                    if pattern is HORIZON and match['side'].lower() == 'below':
                        value = -value
                    values.append((value % 360 if pattern is AZ else value, match))
        compass = False
        if not azimuths:
            azimuths = [(COMPASS[m[1].lower()], m) for m in DIRECTION.finditer(sentence)]
            compass = bool(azimuths)
        # Pair readings only when the passage gives a single value on each axis.
        pairs = [(azimuths[0], elevations[0])] if len(azimuths) == len(elevations) == 1 else (
            [(v, None) for v in azimuths] + [(None, v) for v in elevations])
        for az, el in pairs:
            m = (az or el)[1]
            rows.append(dict(azimuth=az[0] if az else None, elevation=el[0] if el else None,
                             basis='reported compass sector' if az and compass else 'reported angle',
                             excerpt=sentence[max(0, m.start()-140):max(m.end(),(el or az)[1].end())+140].strip()[:650]))
    return rows
