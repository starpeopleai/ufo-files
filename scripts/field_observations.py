"""Typed graph projection of reviewed Field Station evidence, never transcript NLP."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path, PurePosixPath
from urllib.parse import quote

INPUT_SCHEMA = "ufo-files-field-observation/v1"
SCHEMA = "ufo-files-field-observation-graph/v1"
HEX32 = re.compile(r"[a-f0-9]{32}\Z")
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
STATION = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
SESSION = re.compile(r"[0-9TZ]+-[a-f0-9]{6}\Z")
ARCHIVE = re.compile(r"[A-Za-z0-9_.-]{1,200}\Z")
MAX_RECORD_BYTES = 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def token(value, pattern):
    require(isinstance(value, str) and pattern.fullmatch(value), "Invalid evidence identifier")
    return value


def finite(value, minimum=0):
    return type(value) in (int, float) and math.isfinite(value) and value >= minimum


def uid(kind, value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "field-" + kind + ":" + hashlib.sha256(encoded).hexdigest()[:24]


def asset_projection(asset, archive_id):
    name = asset.get("name", "")
    require(isinstance(name, str) and name and "\\" not in name
            and not PurePosixPath(name).is_absolute() and ".." not in PurePosixPath(name).parts,
            "Unsafe Archive asset name")
    allowed = name in {"video.mp4", "video-annotated.mp4", "rf.jsonl",
                       "review-annotations.json", "frames/reviewed-index.json"} or (
        name.startswith("frames/reviewed-") and name.endswith(("-original.png", "-annotated.png")))
    require(allowed, "Unsupported evidence asset")
    url = "https://archive.org/download/" + archive_id + "/" + quote(name, safe="/")
    require(asset.get("url") == url, "Archive asset URL mismatch")
    require(type(asset.get("bytes")) is int and asset["bytes"] >= 0, "Invalid asset size")
    return {"name": name, "url": url, "sha256": token(asset.get("sha256"), HEX64), "bytes": asset["bytes"]}


def load_field_observations(input_root: Path, *, review_data_dir: Path | None = None) -> dict:
    """Rebuild the projection from current records; tombstones cannot leave stale edges.

    Output is constructed from an allowlist. Unknown source fields (including GPS,
    local paths, free-text notes) are never propagated. Malformed active evidence
    fails the build rather than silently disappearing from an apparently complete graph.
    """
    root = Path(input_root) / "Field-Station"
    data_dir = Path(review_data_dir) if review_data_dir is not None else Path(__file__).resolve().parents[1] / "data"
    reviews_path = data_dir / "field_location_reviews.json"
    location_reviews = {}
    review_digest = None
    if reviews_path.exists():
        raw_reviews = reviews_path.read_bytes()
        review_digest = hashlib.sha256(raw_reviews).hexdigest()
        reviews = json.loads(raw_reviews)
        require(reviews.get("schema") == "ufo-files-field-location-reviews/v1", "Invalid location review schema")
        for review in reviews.get("reviews", []):
            require(review.get("method") == "station_operator_confirmation", "Location review needs explicit confirmation")
            for observation_id in review.get("observationIds", []):
                require(observation_id not in location_reviews, "Conflicting location reviews")
                location_reviews[observation_id] = review

    require(not root.is_symlink(), "Observation collection must not be a symlink")
    nodes, edges, observations = {}, {}, []
    statuses = {"published": 0, "withdrawn": 0, "pending_evidence": 0}
    inputs = []

    def node(kind, key, **attributes):
        value = {"id": key, "type": kind, **attributes}
        if key in nodes:
            require(nodes[key] == value, "Conflicting shared evidence node: " + key)
        nodes[key] = value
        return key

    def edge(source, target, relation, provenance, **attributes):
        key = uid("edge", [source, target, relation, provenance["observationId"], attributes.get("originalFrameIndex")])
        edges[key] = {"id": key, "source": source, "target": target,
                      "relation": relation, "provenance": provenance, **attributes}

    paths = []
    if root.exists():
        require(root.is_dir(), "Observation collection must be a directory")
        def walk_error(error):
            raise ValueError("Cannot enumerate observation collection") from error
        for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
            for name in dirs + files:
                require(not (Path(directory) / name).is_symlink(), "Symlink in observation collection")
            paths.extend(Path(directory) / name for name in files if name.endswith(".json"))
    for path in sorted(paths):
        relative = path.relative_to(root)
        require(len(relative.parts) == 2, "Unexpected observation path: " + str(relative))
        require(path.is_file() and path.stat().st_size <= MAX_RECORD_BYTES, "Invalid observation file size")
        raw = path.read_bytes()
        record = json.loads(raw)
        require(isinstance(record, dict) and record.get("schema") == INPUT_SCHEMA, "Unsupported observation schema")
        station = token(record.get("station_id"), STATION)
        event = token(record.get("capture_event_id"), HEX32)
        oid = "field:" + station + ":" + event
        require(relative.parts == (station, event + ".json") and record.get("id") == oid, "Observation path/identity mismatch")
        require(type(record.get("revision")) is int and record["revision"] > 0, "Invalid observation revision")
        epoch = token(record.get("source_epoch"), HEX32)
        status = record.get("status")
        require(status in statuses, "Unsupported observation status")
        statuses[status] += 1
        checksum = hashlib.sha256(raw).hexdigest()
        source_path = "Field-Station/" + relative.as_posix()
        inputs.append([source_path, checksum])
        if status != "published":
            continue
        require(record.get("human_classification") == "anomalous"
                and record.get("review_scope") == "human_reviewed_objects", "Missing human review")
        require(record.get("recordings") and record.get("annotations") and record.get("archive_bundles"), "Incomplete reviewed evidence")
        provenance = {"observationId": oid, "sourcePath": source_path, "sourceSha256": checksum,
                      "revision": record["revision"], "sourceEpoch": epoch}
        node("observation", oid, classification="anomalous", classificationSource="human_review")
        station_node = node("station", "field-station:" + station, stationId=station)
        edge(oid, station_node, "observed_by", provenance)
        recording_ids = {}
        for recording in record["recordings"]:
            rid = token(recording.get("id"), SESSION)
            require(rid not in recording_ids, "Duplicate recording in observation")
            family = "field-recording:" + station + ":" + rid
            require(recording.get("source_family_id") == family, "Recording family mismatch")
            require(recording.get("capture_kind") in {"manual", "automatic"}, "Invalid recording kind")
            attributes = {"recordingId": rid, "sourceFamilyId": family, "captureKind": recording["capture_kind"]}
            for key, output in [("started_epoch", "startedEpoch"), ("stopped_epoch", "stoppedEpoch"), ("video_fps", "videoFps")]:
                value = recording.get(key)
                require(value is None or finite(value), "Invalid recording timing")
                attributes[output] = value
            if attributes["startedEpoch"] is not None and attributes["stoppedEpoch"] is not None:
                require(attributes["stoppedEpoch"] >= attributes["startedEpoch"], "Reversed recording window")
            recording_ids[rid] = node("recording", family, **attributes)
            edge(oid, family, "captured_in", provenance)
        bundles = []
        bundled_recordings = set()
        for bundle in record["archive_bundles"]:
            rid = bundle.get("recording_id")
            require(rid in recording_ids, "Evidence refers to an unknown recording")
            aid = token(bundle.get("identifier"), ARCHIVE)
            url = "https://archive.org/details/" + aid
            require(bundle.get("url") == url and finite(bundle.get("verified_epoch"), 1), "Unverified Archive evidence")
            review_revision = token(bundle.get("review_revision"), HEX64)
            assets = [asset_projection(asset, aid) for asset in bundle.get("assets", [])]
            require(any(asset["name"] == "video.mp4" for asset in assets), "Original video evidence missing")
            bundle_node = node("archive_bundle", "archive:" + aid, identifier=aid, url=url)
            edge(oid, bundle_node, "evidenced_by", provenance, reviewRevision=review_revision,
                 verifiedEpoch=bundle["verified_epoch"])
            bundles.append({"nodeId": bundle_node, "recordingId": rid, "reviewRevision": review_revision,
                            "verifiedEpoch": bundle["verified_epoch"], "assets": assets})
            bundled_recordings.add(rid)
        annotation_ids = []
        for annotation in record["annotations"]:
            aid = token(annotation.get("id"), HEX32)
            require(annotation.get("classification") == "anomalous" and finite(annotation.get("reviewed_epoch"), 1), "Invalid annotation review")
            bounds = annotation.get("bounds_pixels")
            require(isinstance(bounds, list) and len(bounds) == 4 and all(finite(v) for v in bounds)
                    and min(bounds[2:]) > 0, "Invalid review box")
            key = "field-object:" + station + ":" + aid
            require(key not in annotation_ids, "Duplicate annotation")
            node("reviewed_object", key, annotationId=aid, classification="anomalous",
                 reviewedEpoch=annotation["reviewed_epoch"], boundsPixels=bounds,
                 cropSha256=token(annotation.get("crop_sha256"), HEX64))
            annotation_ids.append(key)
            edge(oid, key, "has_reviewed_object", provenance)
            require(annotation.get("frame_references"), "Missing annotation frame")
            for ref in annotation["frame_references"]:
                rid, frame = ref.get("recording_id"), ref.get("original_frame_index")
                require(rid in bundled_recordings and type(frame) is int and frame >= 0, "Invalid annotation frame reference")
                edge(key, recording_ids[rid], "reviewed_frame_in", provenance, originalFrameIndex=frame)
        model = record.get("original_prediction")
        if model is not None:
            require(model.get("scope") == "original_capture_prediction", "Invalid model prediction scope")
            model_hash = token(model.get("model_sha256"), HEX64)
            model_node = node("model", "field-model:" + model_hash, sha256=model_hash)
            prediction = {}
            if "classification" in model:
                require(model["classification"] in {"anomalous", "not_anomalous"}, "Invalid original classification")
                prediction["classification"] = model["classification"]
            if "score" in model:
                require(finite(model["score"]), "Invalid model score")
                prediction["score"] = model["score"]
            edge(oid, model_node, "predicted_by", provenance, scope=model["scope"], **prediction)
        location = record.get("location", {})
        location_source = "capture_metadata"
        location_review = location_reviews.get(oid)
        if location_review:
            coarse_review = {k: location_review[k] for k in ("county", "state", "country")}
            if location.get("status") == "known":
                require(all(location.get(k) == v for k, v in coarse_review.items()), "Capture location conflicts with confirmed historical location")
            else:
                location = {"status": "known", "precision": "county", **coarse_review}
                location_source = "station_operator_confirmation"

        require(location.get("precision") == "county" and location.get("status") in {"known", "unknown"}, "Invalid location precision")
        if location["status"] == "known":
            coarse = {key: location.get(key) for key in ("county", "state", "country")}
            require(all(isinstance(v, str) and 0 < len(v) <= 120 and not any(ord(c) < 32 for c in v) for v in coarse.values()), "Invalid county region")
            region = node("county_region", uid("region", coarse), precision="county", **coarse)
            edge(oid, region, "located_in", provenance, precision="county", locationSource=location_source,
                 **({"locationReviewId": location_review["id"], "locationReviewSha256": review_digest}
                    if location_source == "station_operator_confirmation" else {}))
        context = record.get("ce5_playback", {"state": "unknown"})
        require(context.get("state") in {"on", "off", "unknown"}, "Invalid playback context")
        playback = {"state": context["state"]}
        if "observed_overlap_seconds" in context:
            require(finite(context["observed_overlap_seconds"]), "Invalid playback overlap")
            playback["observedOverlapSeconds"] = context["observed_overlap_seconds"]
        pose = record.get("camera_pointing")
        pointing = {}
        if pose is not None:
            require(isinstance(pose, dict) and finite(pose.get("azimuth_deg")) and pose["azimuth_deg"] < 360
                    and finite(pose.get("elevation_deg"), -90) and pose["elevation_deg"] <= 90
                    and finite(pose.get("settings_epoch"), 1) and finite(pose.get("detected_epoch"), pose["settings_epoch"]),
                    "Invalid capture-time camera pointing")
            pointing = {"cameraPointing": {"azimuth": pose["azimuth_deg"], "elevation": pose["elevation_deg"],
                                          "detectedEpoch": pose["detected_epoch"]}}
        observations.append({**pointing, "id": oid, "provenance": provenance, "reviewedObjectIds": annotation_ids,
                             "recordingIds": sorted(recording_ids.values()), "evidence": bundles,
                             "ce5Playback": playback})
    regions_path = data_dir / "field_regions.json"
    region_references = []
    if regions_path.exists():
        reference = json.loads(regions_path.read_text())
        require(reference.get("schema") == "ufo-files-county-boundaries/v1", "Invalid county boundary schema")
        for n in nodes.values():
            if n["type"] != "county_region":
                continue
            matches = [r for r in reference["regions"] if all(r.get(k) == n[k] for k in ("county", "state", "country"))]
            require(len(matches) <= 1, "Ambiguous county boundary")
            if matches:
                region_references.append({"id": n["id"], **matches[0]})
    return {
        "schema": SCHEMA,
        "scope": "Human-reviewed anomalous objects with verified Archive evidence; not transcript claims or proof of cause",
        "policy": {"locations": "County boundaries only; no station coordinates or inferred station points",
                   "time": "Recording coverage is not an exact sighting time or duration",
                   "sourceFamilies": "Shared recordings do not constitute independent corroboration",
                   "rf": "Linked recorded evidence only; distinct from frequency mentions in transcripts",
                   "playback": "Measured context, not a causal relationship"},
        "input": {"collection": "Field-Station", "present": root.is_dir(), "digest": uid("input", inputs)},
        "counts": {"records": sum(statuses.values()), **statuses, "observations": len(observations),
                   "reviewedObjects": sum(n["type"] == "reviewed_object" for n in nodes.values()),
                   "recordings": sum(n["type"] == "recording" for n in nodes.values()),
                   "stations": sum(n["type"] == "station" for n in nodes.values()),
                   "nodes": len(nodes), "edges": len(edges)},
        "regions": region_references,
        "observations": observations,
        "nodes": sorted(nodes.values(), key=lambda n: n["id"]),
        "edges": sorted(edges.values(), key=lambda e: e["id"]),
    }
