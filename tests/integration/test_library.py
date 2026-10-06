import io

import httpx
import numpy as np
import soundfile as sf

from tests.integration.conftest import wait_for


def wav_bytes(seconds=0.4, sr=44100, f=200.0):
    t = np.arange(int(seconds * sr)) / sr
    buf = io.BytesIO()
    sf.write(buf, 0.6 * np.sin(2 * np.pi * f * t) * np.exp(-t * 12), sr, format="WAV", subtype="PCM_24")
    return buf.getvalue()


def test_upload_render_and_serve(procs):
    url = procs.api()
    procs.worker()
    # upload: role guessed from the name, route follows the role, duplicates are recognised by sha256
    files = [
        ("files", ("snare_04 crack.wav", wav_bytes(), "audio/wav")),
        ("files", ("loop_rhodes.wav", wav_bytes(1.0, 48000, 330), "audio/wav")),
    ]
    up = httpx.post(url + "/api/samples", files=files).json()["samples"]
    snare = next(s for s in up if s["name"].startswith("snare"))
    loop = next(s for s in up if s["name"].startswith("loop"))
    assert (snare["role"], snare["route"]) == ("snare", "sp") and (loop["role"], loop["route"]) == ("other", "mpc")
    again = httpx.post(url + "/api/samples", files=[("files", ("x.wav", wav_bytes(), "audio/wav"))]).json()
    assert again["samples"][0]["id"] == snare["id"] and again["samples"][0]["created"] is False
    bad = httpx.post(url + "/api/samples", files=[("files", ("x.txt", b"not audio", "text/plain"))])
    assert bad.status_code == 415

    assert httpx.patch(f"{url}/api/samples/{loop['id']}", json={"route": "sp"}).json()["route"] == "sp"
    peaks = httpx.get(f"{url}/api/samples/{snare['id']}/peaks?n=64").json()
    assert len(peaks) == 64 and all(lo <= hi for lo, hi in peaks)

    presets = {p["name"]: p for p in httpx.get(url + "/api/presets").json()}
    assert {"sp_snare_hard", "sp_kick_low", "mpc_nl_pwl"} <= set(presets)

    body = {"sample_id": snare["id"], "preset_id": presets["sp_snare_hard"]["id"], "overrides": {"tune": {"st": -1}}}
    jid = httpx.post(url + "/api/jobs", json=body).json()["id"]

    def job():
        return next(j for j in httpx.get(url + "/api/snapshot").json()["jobs"] if j["id"] == jid)

    wait_for(lambda: job()["state"] == "succeeded", 30, "render succeeded")
    j = job()
    assert j["output_name"] == "snare_04_crack__sp-snare-hard__tune-1.wav" and j["tune"] == -1
    assert [s["name"] for s in j["stages"]] == [
        "role",
        "pre_eq",
        "drive",
        "capture",
        "adc",
        "tune",
        "vol_env",
        "dac",
        "analog",
        "output",
    ]
    assert all(s["state"] == "succeeded" for s in j["stages"])

    wav = httpx.get(f"{url}/api/jobs/{jid}/files/wav")
    assert wav.status_code == 200 and "snare_04_crack__sp-snare-hard__tune-1.wav" in wav.headers["content-disposition"]
    info = sf.info(io.BytesIO(wav.content))
    assert info.samplerate == 48000 and info.subtype == "PCM_24"
    # iOS Safari needs byte ranges
    part = httpx.get(f"{url}/api/jobs/{jid}/files/wav", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100
    assert httpx.get(f"{url}/api/samples/{snare['id']}/audio", headers={"Range": "bytes=10-19"}).status_code == 206
    assert httpx.get(f"{url}/api/jobs/{jid}/files/png").headers["content-type"] == "image/png"
    meta = httpx.get(f"{url}/api/jobs/{jid}/params").json()
    assert meta["params"]["tune"]["st"] == -1 and meta["params_annotated"]["sp.adc.aa"]["status"] == "HYP"

    renders = httpx.get(f"{url}/api/samples/{snare['id']}/renders").json()
    assert renders[0]["id"] == jid
    # a sample with renders cannot be deleted; one without can
    assert httpx.delete(f"{url}/api/samples/{snare['id']}").status_code == 409
    assert httpx.delete(f"{url}/api/samples/{loop['id']}").status_code == 200


def test_mpc_render_and_preset_versions(procs):
    url = procs.api()
    procs.worker()
    up = httpx.post(url + "/api/samples", files=[("files", ("vox.wav", wav_bytes(0.5, 48000, 440), "audio/wav"))])
    sample = up.json()["samples"][0]
    saved = httpx.post(
        url + "/api/presets", json={"name": "my_mpc", "path": "mpc", "params": {"codec": {"curve": "mulaw"}}}
    ).json()
    again = httpx.post(url + "/api/presets", json={"name": "my_mpc", "path": "mpc", "params": {}}).json()
    assert (saved["version"], again["version"]) == (1, 2)
    assert saved["params"]["codec"]["curve"] == "mulaw" and saved["params"]["output"]["rate"] == 48000
    jid = httpx.post(url + "/api/jobs", json={"sample_id": sample["id"], "preset_id": saved["id"]}).json()["id"]
    wait_for(
        lambda: (
            next(j for j in httpx.get(url + "/api/snapshot").json()["jobs"] if j["id"] == jid)["state"] == "succeeded"
        ),
        30,
        "mpc render",
    )
    j = next(j for j in httpx.get(url + "/api/snapshot").json()["jobs"] if j["id"] == jid)
    assert [s["name"] for s in j["stages"]] == ["input", "resample", "nl12_codec", "tune", "deemph_dac"]
