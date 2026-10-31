"""Скачать модель для поиска лиц (нужна для мягкой ретуши)."""

from photo_agent.face_detect import model_status

if __name__ == "__main__":
    ok, info = model_status()
    if ok:
        print("OK:", info)
    else:
        print("ERROR:", info)
