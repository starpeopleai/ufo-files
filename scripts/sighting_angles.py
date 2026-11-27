"""Identify explicitly reported viewing angles in sighting passages."""
import re

VALUE = r"(?<![\d.−-])(?P<n>[+−-]?\d{1,3}(?:\.\d+)?)(?!\d|\.\d)"
UNIT = r"\s*(?:°|deg(?:ree)?s?\b)"
AZ = re.compile(r"\b(?:azimuth|bearing)\s*(?:of\s+|was\s+|[:=]\s*)?" + VALUE, re.I)
EL = re.compile(r"\b(?:elevation(?:\s+angle)?|angle\s+of\s+elevation)\s*(?:of\s+|was\s+|[:=]\s*)?" + VALUE + UNIT, re.I)
AZ_AFTER = re.compile(VALUE + UNIT + r"\s+(?:in\s+)?azimuth\b", re.I)
EL_AFTER = re.compile(VALUE + UNIT + r"\s+(?:(?:of|in)\s+)?elevation\b", re.I)
# Blue Book teletype reports sometimes give angular altitude after an object bearing.
ALT = re.compile(r"\baltitude\s*(?:of\s+|[:=]\s*)?" + VALUE + UNIT, re.I)
AZ_SHORT = re.compile(VALUE + UNIT + r"\s+az\b", re.I)
EL_SHORT = re.compile(VALUE + UNIT + r"\s+elev\b", re.I)
PHASE = re.compile(r"\b(?:first seen|last seen|first sighted|last sighted|disappeared|reappeared)\b", re.I)
REFERENCE_BODY = re.compile(r"\b(?:sun|moon|venus|vinus|jupiter|mars)\s+(?:was|would be|had been|lay)\s+(?:at|on)\b", re.I)
MOTION = re.compile(r"(?:travel(?:l?ing|led)|moving|flew|course|heading)\s+(?:(?:on|at|a|an|of)\s+)*$", re.I)
HORIZON = re.compile(VALUE + UNIT + r"\s+(?P<side>above|below)\s+(?:the\s+)?horizon\b", re.I)
COMPASS = dict(north=0, northeast=45, east=90, southeast=135, south=180, southwest=225, west=270, northwest=315)
DIRECTION = re.compile(r"\b(?:looking|facing|looked|in\s+the|to\s+the)\s+(?:towards?\s+)?(north(?:east|west)?|south(?:east|west)?|east|west)\b", re.I)
SIGHT = re.compile(r"\b(?:saw|sighting|observed|witness(?:ed)?|object|light[s]?|ufo|uap|orb)\b", re.I)


def reported_angles(text, *, blue_book=False):
    if not SIGHT.search(text) and not (blue_book and PHASE.search(text)):
        return []
    rows = []
    for sentence in re.split(r"(?<=[.!?])\s+|[;\n]", text):
        if not SIGHT.search(sentence) and not (blue_book and PHASE.search(sentence)):
            continue
        if REFERENCE_BODY.search(sentence):
            continue
        azimuths, elevations = [], []
        candidates = []
        ranges = [m.span() for m in re.finditer(r"\d+(?:\.\d+)?\s*(?:[-–—]|to)\s*\d+(?:\.\d+)?", sentence, re.I)]
        patterns = [
                (AZ, azimuths, 0, 360), (AZ_AFTER, azimuths, 0, 360),
                (EL, elevations, -90, 90), (EL_AFTER, elevations, -90, 90),
                (HORIZON, elevations, 0, 90)]
        if blue_book:
            patterns.extend([(AZ_SHORT, azimuths, 0, 360), (EL_SHORT, elevations, -90, 90)])
            if AZ.search(sentence):
                patterns.append((ALT, elevations, -90, 90))
        for pattern, values, lower, upper in patterns:
            for match in pattern.finditer(sentence):
                if values is azimuths and MOTION.search(sentence[:match.start()]):
                    continue
                value = float(match['n'].replace('−', '-'))
                if not lower <= value <= upper or any(start < match.end('n') and end > match.start('n') for start, end in ranges):
                    continue
                if pattern is HORIZON and match['side'].lower() == 'below':
                    value = -value
                candidates.append((match, values, value % 360 if values is azimuths else value))
        end = 0
        for match, values, value in sorted(candidates, key=lambda item: item[0].start()):
            if match.start() >= end:
                values.append((value, match))
                end = match.end()
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

def blue_book_case_pdf(relative):
    return re.match(r"^National-Archives-UAP-Bulk/documents/597821-pdfs-[1-5]/", relative) is not None
