"""Instagram dışa aktarımındaki bekleyen istekleri görünür tarayıcıyla iptal et."""
import argparse
import json
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path


class UsernameParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cells = []
        self.cell = None
        self.users = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.cells = []
        elif tag == "td":
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == "td" and self.cell is not None:
            self.cells.append("".join(self.cell).strip())
            self.cell = None
        elif tag == "tr" and len(self.cells) == 2:
            if self.cells[0].casefold() in ("kullanıcı adı", "username"):
                username = self.cells[1].strip()
                if not re.fullmatch(r"[A-Za-z0-9_.]{1,30}", username):
                    raise ValueError(f"Geçersiz kullanıcı adı: {username!r}")
                if username.lower() not in {u.lower() for u in self.users}:
                    self.users.append(username)


def read_users(path):
    parser = UsernameParser()
    parser.feed(path.read_text(encoding="utf-8-sig"))
    if not parser.users:
        raise ValueError("HTML içinde Kullanıcı adı satırı bulunamadı.")
    return parser.users


REQUESTED = re.compile(r"^(Requested|İstek gönderildi|İstek Gönderildi|Talep edildi)$", re.I)
FOLLOW = re.compile(r"^(Follow|Follow back|Takip et|Geri takip et)$", re.I)
FOLLOWING = re.compile(r"^(Following|Takiptesin|Takip ediliyor)$", re.I)
CANCEL = re.compile(r"^\s*(Cancel request|Cancel follow request|Cancel follow|İsteği iptal et|Takip isteğini iptal et|İstek iptal|İsteği geri çek)\s*$", re.I)
# Bazı sürümlerde bekleyen isteğin onayı da bu adla gösterilir.
# Yalnızca Requested düğmesinden sonra açılan dialog içinde kullanılabilir.
UNFOLLOW_CONFIRM = re.compile(r"^\s*(Unfollow|Takibi bırak|Takipten çık)\s*$", re.I)
WARNINGS = re.compile(
    r"try again later|we restrict certain activity|action blocked|automated behavio[u]?r|"
    r"confirm (?:your identity|it's you)|suspicious activity|"
    r"daha sonra tekrar dene|bazı hareketleri kısıtlıyoruz|işlem engellendi|"
    r"otomatik davranış|kimliğini doğrula|şüpheli hareket", re.I
)


class SessionStopped(RuntimeError):
    """Profil değiştirerek çözülemeyen oturum veya hesap hatası."""


def guard(page):
    if any(p in page.url for p in ("/accounts/login", "/challenge", "/checkpoint")):
        raise SessionStopped("Giriş veya güvenlik doğrulaması gerekiyor; işlem durduruldu.")
    if WARNINGS.search(page.locator("body").inner_text()):
        raise SessionStopped("Instagram kısıtlama/güvenlik uyarısı gösterdi; işlem durduruldu.")


def visible_button(scope, pattern):
    matches = scope.get_by_role("button", name=pattern)
    visible = [matches.nth(i) for i in range(matches.count()) if matches.nth(i).is_visible()]
    if len(visible) > 1:
        raise RuntimeError("Birden fazla eşleşen düğme bulundu; güvenli seçim yapılamadı.")
    return visible[0] if visible else None


def save_diagnostics(page):
    root = Path(__file__).resolve().parent
    buttons = page.get_by_role("button")
    labels = [buttons.nth(i).inner_text() for i in range(buttons.count())
              if buttons.nth(i).is_visible()]
    path = root / "cancel_requests_debug.json"
    path.write_text(json.dumps({"url": page.url, "buttons": labels},
                               ensure_ascii=False, indent=2), encoding="utf-8")
    page.screenshot(path=str(root / "cancel_requests_debug.png"))
    print(f"Tanı dosyaları kaydedildi: {path.name}, cancel_requests_debug.png")


def request_removed(page):
    # Önerilen hesapların da Takip Et düğmeleri vardır. Sonuç kontrolü
    # düğme seçip tıklamaz; bu yüzden birden fazla Follow eşleşmesi normaldir.
    if visible_button(page, REQUESTED) is not None:
        return False
    matches = page.get_by_role("button", name=FOLLOW)
    return any(matches.nth(i).is_visible() for i in range(matches.count()))


def confirm_cancellation(page):
    # Onayın yüklenmesini bekle; Requested düğmesine tekrar tıklama.
    for _ in range(15):
        guard(page)
        if request_removed(page):
            return
        dialogs = page.get_by_role("dialog")
        visible_dialogs = [dialogs.nth(i) for i in range(dialogs.count())
                           if dialogs.nth(i).is_visible()]
        scope = visible_dialogs[0] if len(visible_dialogs) == 1 else page
        cancel = visible_button(scope, CANCEL)
        if cancel is None and len(visible_dialogs) == 1:
            cancel = visible_button(scope, UNFOLLOW_CONFIRM)
        if cancel is not None:
            cancel.click()
            return
        page.wait_for_timeout(1000)

    raise RuntimeError("İptal onayı otomatik tanınamadı.")


def cancel_one(page, username):
    response = page.goto(f"https://www.instagram.com/{username}/", wait_until="domcontentloaded")
    if response and response.status == 429:
        raise SessionStopped("Instagram HTTP 429 (istek sınırı) döndürdü.")
    if response and response.status >= 400:
        raise RuntimeError(f"Profil HTTP {response.status} döndürdü.")
    page.wait_for_timeout(4000)
    guard(page)
    requested = visible_button(page, REQUESTED)
    if requested is None:
        if visible_button(page, FOLLOWING):
            return "already_following"
        if request_removed(page):
            return "no_pending_request"
        raise RuntimeError("Beklenen profil düğmeleri bulunamadı; arayüzü kontrol edin.")
    requested.click()
    confirm_cancellation(page)
    for _ in range(15):
        page.wait_for_timeout(1000)
        guard(page)
        if request_removed(page):
            return "cancelled"
    raise RuntimeError("İptal sonucu doğrulanamadı; işlem durduruldu.")


def save_state(path, state):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def remaining_users(users, state, retry_errors=False):
    return [u for u in users if u.lower() not in state["done"]
            and (retry_errors or u.lower() not in state.get("errors", {}))]


def process_profile(page, user, state, state_path, errors_path):
    try:
        result = cancel_one(page, user)
    except Exception as exc:
        record = {"username": user, "url": f"https://www.instagram.com/{user}/",
                  "error": str(exc), "type": type(exc).__name__,
                  "time": datetime.now(timezone.utc).isoformat()}
        state.setdefault("errors", {})[user.lower()] = record
        save_state(state_path, state)
        with errors_path.open("a", encoding="utf-8") as log:
            log.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"  HATA: {exc} — kaydedildi: {errors_path.name}", flush=True)
        if isinstance(exc, SessionStopped) or page.is_closed():
            raise
        return False
    state["done"][user.lower()] = {"result": result,
                                  "time": datetime.now(timezone.utc).isoformat()}
    state.setdefault("errors", {}).pop(user.lower(), None)
    save_state(state_path, state)
    print(f"  {result}", flush=True)
    return True


def main():
    print("Sürüm: 2026-10-02.3 (devam etme ve hata kaydı)", flush=True)
    print(f"Çalıştırılan dosya: {Path(__file__).resolve()}", flush=True)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("html", nargs="?", type=Path, default=Path(__file__).with_name("pending_follow_requests.html"))
    ap.add_argument("--dry-run", action="store_true", help="Yalnızca profil adreslerini listele")
    ap.add_argument("--delay", type=int, default=5, help="Profiller arası saniye (varsayılan 5, en az 1)")
    ap.add_argument("--batch-size", type=int, default=10, help="Grup molası öncesi profil sayısı")
    ap.add_argument("--break-seconds", type=int, default=30, help="Grup molası saniyesi (varsayılan 30; 0 kapatır)")
    ap.add_argument("--retry-errors", action="store_true", help="Önceki çalıştırmalarda hata veren profilleri de yeniden dene")
    args = ap.parse_args()
    if args.delay < 1 or args.batch_size < 1 or args.break_seconds < 0:
        ap.error("Bekleme en az 1 sn, grup en az 1 profil, grup molası en az 0 sn olmalı.")
    users = read_users(args.html)
    print(f"HTML içinde {len(users)} benzersiz kullanıcı bulundu.")
    if args.dry_run:
        for user in users:
            print(f"https://www.instagram.com/{user}/")
        return
    from playwright.sync_api import sync_playwright

    root = Path(__file__).resolve().parent
    state_path = root / "cancel_requests_progress.json"
    errors_path = root / "cancel_requests_errors.jsonl"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"account_id": None, "done": {}}
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(str(root / ".instagram_browser"), headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(15000)
        try:
            page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
            input("Tarayıcıda kendi hesabına manuel giriş yap, bildirim pencerelerini kapat. Hazır olduğunda burada Enter: ")
            guard(page)
            cookies = context.cookies("https://www.instagram.com/")
            account = next((c["value"] for c in cookies if c["name"] == "ds_user_id"), None)
            if not account:
                raise RuntimeError("Oturum doğrulanamadı; giriş yapıldığından emin olun.")
            if state["account_id"] not in (None, account):
                raise RuntimeError("İlerleme dosyası başka hesaba ait. Ayrı klasör kullanın.")
            state["account_id"] = account
            save_state(state_path, state)
            pending = remaining_users(users, state, args.retry_errors)
            print(f"Kaydedilen ilerleme kullanılıyor: {len(users) - len(pending)} profil atlandı, {len(pending)} profil kaldı.", flush=True)
            for index, user in enumerate(pending, 1):
                print(f"[{index}/{len(pending)}] {user}", flush=True)
                process_profile(page, user, state, state_path, errors_path)
                if index < len(pending):
                    delay = max(args.delay, args.break_seconds) if index % args.batch_size == 0 else args.delay
                    print(f"{delay} saniye mola. Durdurmak için Ctrl+C.", flush=True)
                    time.sleep(delay)
            unresolved = sum(u.lower() in state.get("errors", {}) for u in users)
            print(f"Liste tamamlandı. Hatalı profil: {unresolved}. Yeniden denemek için --retry-errors kullanın.")
        except KeyboardInterrupt:
            print("Durduruldu. Kaydedilen ilerleme sonraki çalıştırmada kullanılacak.")
        except Exception as exc:
            print(f"DURDURULDU: {exc}")
            raise SystemExit(1) from exc
        finally:
            context.close()


if __name__ == "__main__":
    main()
