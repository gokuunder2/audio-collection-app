import os

from pydub import AudioSegment  # type: ignore[import-not-found]


def analyze_audio(filepath):

    audio = None

    try:

        audio = AudioSegment.from_file(filepath)

        duration_sec = round(
            len(audio) / 1000.0,
            3
        )

        sample_rate_hz = audio.frame_rate

        sample_rate_khz = round(
            sample_rate_hz / 1000.0,
            2
        )

        channels = audio.channels

        sample_width_bits = (
            audio.sample_width * 8
        )

        file_size_bytes = os.path.getsize(
            filepath
        )

        bitrate_kbps = (
            round(
                (file_size_bytes * 8)
                / duration_sec
                / 1000,
                1
            )
            if duration_sec > 0
            else 0
        )

        loudness_dbfs = audio.dBFS

        if loudness_dbfs == float("-inf"):
            loudness_dbfs = -96.0

        loudness_dbfs = round(
            loudness_dbfs,
            2
        )

        peak_dbfs = audio.max_dBFS

        if peak_dbfs == float("-inf"):
            peak_dbfs = -96.0

        peak_dbfs = round(
            peak_dbfs,
            2
        )

        noise_floor_dbfs, snr_db = estimate_noise(
            audio
        )

        quality_label = classify_quality(
            snr_db
        )

        return {
            "duration_sec": duration_sec,
            "sample_rate_hz": sample_rate_hz,
            "sample_rate_khz": sample_rate_khz,
            "channels": channels,
            "sample_width_bits": sample_width_bits,
            "bitrate_kbps": bitrate_kbps,
            "loudness_dbfs": loudness_dbfs,
            "peak_dbfs": peak_dbfs,
            "noise_floor_dbfs": (
                round(noise_floor_dbfs, 2)
                if noise_floor_dbfs is not None
                else None
            ),
            "snr_db": (
                round(snr_db, 2)
                if snr_db is not None
                else None
            ),
            "quality_label": quality_label,
        }

    finally:

        # Release the Pydub object.
        audio = None


def estimate_noise(audio, chunk_ms=50):

    if len(audio) < chunk_ms * 5:
        return None, None

    FLOOR_DBFS = -90.0

    chunks = [
        audio[i:i + chunk_ms]
        for i in range(
            0,
            len(audio),
            chunk_ms
        )
    ]

    levels = sorted(
        FLOOR_DBFS
        if c.dBFS == float("-inf")
        else c.dBFS
        for c in chunks
    )

    if len(levels) < 5:
        return None, None

    idx_10 = max(
        0,
        int(len(levels) * 0.10)
    )

    idx_90 = min(
        len(levels) - 1,
        int(len(levels) * 0.90)
    )

    noise_floor = levels[idx_10]

    signal_level = levels[idx_90]

    snr = signal_level - noise_floor

    return noise_floor, snr


def classify_quality(snr_db):

    if snr_db is None:
        return "unknown"

    if snr_db >= 30:
        return "good"

    if snr_db >= 15:
        return "moderate"

    return "poor"