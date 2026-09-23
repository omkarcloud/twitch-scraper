"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json.
"""
import json
import os

from twitch import channels, clips, directory

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # a login, numeric id or any twitch.tv channel link
    save("channel_kaicenat.json", channels.details({"login": "kaicenat"}))

    # the live directory, filtered by language (30 per page, cursor paging)
    save("top_streams_en.json", directory.streams(languages=["en"], limit=30))

    # a clip with its MP4 download links
    save("clip_kevin_hart.json", clips.details("FaintCrazyEyeballMcaT-NQXM-eo18gDGQSDh"))
