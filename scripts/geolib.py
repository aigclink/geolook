"""GEO 工具箱共用模块：路径、配置、HTTP、正文抽取。

只依赖 requests / bs4 / lxml（标准 macOS Python 环境已有），不引入 yaml/jinja2。
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"

# 人類可讀輸出一律使用繁體中文（台灣）。這份字形表與 UI 的 zh-TW
# 轉換表採相同範圍，避免新增 OpenCC 等執行階段依賴。
ZHTW_FROM = "万与专业东丢两严个临为举么义习书买乱争于亏云产亿仅从仓们价众优会传伤体余侧储儿关兴内册写决况净准减凑几凭击划则刚创删别剥办务动势区协单占却厂历压参双发变叠台号后吗听启员响团园围国图场坏块声壳处备复够头夸宁宝实审对导将尔尸层属币师带帮干并库应开异弃张弹强归当录径忆态总恒悬惩惯愿戏战户托执扩扫扰抢护报担拟拥拦择挂挡挤损换据携撑数斗断无旧时显暂术机杀杂权杠条来极构栅标栏树样档检槛横残气汇汉没浅测浏涨满滤滥灭点状独环现画监盖盘着码础确礼离种积称稳竖竞笔筛签简类纠约级纪纯纲纳线组细织终经绑结给绝统继绪续维综缀编缘网罚联脑脚脱腾节范荐获营蓝虑补装见观规视览触计订认讨让议讯记讲许论设访证评识诉诊词译试诚话询该详语误说请诺读谁调谱负责败账质购贴费资赖赢趋踪车转轮软轻载较辑输边达过运还这进远连迟适选递逻邻采释里鉴钟钥钱钻铺链销锁锋错锚键长门闭问间闻阅阈队阳阵阶际险随隐难静页顶项顺须顾顿预领颈频题额风饰马驱验骗骤齐"
ZHTW_TO = "萬與專業東丟兩嚴個臨為舉麼義習書買亂爭於虧雲產億僅從倉們價眾優會傳傷體餘側儲兒關興內冊寫決況淨準減湊幾憑擊劃則剛創刪別剝辦務動勢區協單佔卻廠歷壓參雙發變疊臺號後嗎聽啟員響團園圍國圖場壞塊聲殼處備復夠頭誇寧寶實審對導將爾屍層屬幣師帶幫幹並庫應開異棄張彈強歸當錄徑憶態總恆懸懲慣願戲戰戶託執擴掃擾搶護報擔擬擁攔擇掛擋擠損換據攜撐數鬥斷無舊時顯暫術機殺雜權槓條來極構柵標欄樹樣檔檢檻橫殘氣匯漢沒淺測瀏漲滿濾濫滅點狀獨環現畫監蓋盤著碼礎確禮離種積稱穩豎競筆篩籤簡類糾約級紀純綱納線組細織終經綁結給絕統繼緒續維綜綴編緣網罰聯腦腳脫騰節範薦獲營藍慮補裝見觀規視覽觸計訂認討讓議訊記講許論設訪證評識訴診詞譯試誠話詢該詳語誤說請諾讀誰調譜負責敗賬質購貼費資賴贏趨蹤車轉輪軟輕載較輯輸邊達過運還這進遠連遲適選遞邏鄰採釋裡鑑鍾鑰錢鑽鋪鏈銷鎖鋒錯錨鍵長門閉問間聞閱閾隊陽陣階際險隨隱難靜頁頂項順須顧頓預領頸頻題額風飾馬驅驗騙驟齊"
ZHTW_TERMS = (
    ("生成式引擎優化平臺", "生成式引擎最佳化平台"), ("搜尋引擎優化", "搜尋引擎最佳化"),
    ("接入新品牌", "新增品牌"), ("接入引導", "新增品牌引導"), ("國內引擎", "中國引擎"),
    ("國內市場", "中國市場"), ("人工智能", "人工智慧"), ("文件夾", "資料夾"),
    ("手機號", "手機號碼"), ("源代碼", "原始碼"), ("工作臺", "工作台"),
    ("後臺", "後台"), ("平臺", "平台"), ("舞臺", "舞台"), ("數據", "資料"),
    ("信息", "資訊"), ("信源", "資訊來源"), ("陣地", "通路"), ("渠道", "通路"),
    ("設置", "設定"), ("配置", "設定"), ("項目", "專案"), ("保存", "儲存"),
    ("文件", "檔案"), ("網絡", "網路"), ("鏈接", "連結"), ("賬號", "帳號"),
    ("用戶", "使用者"), ("創建", "建立"), ("添加", "新增"), ("加載", "載入"),
    ("導入", "匯入"), ("導出", "匯出"), ("運行", "執行"), ("訪問", "存取"),
    ("代碼", "程式碼"), ("質量", "品質"), ("視頻", "影片"), ("反饋", "回饋"),
    ("服務器", "伺服器"), ("鼠標", "滑鼠"), ("日誌", "紀錄"), ("內存", "記憶體"),
    ("搜索", "搜尋"), ("點擊", "點選"), ("刷新", "重新整理"), ("優化", "最佳化"),
    ("接口", "介面"), ("字段", "欄位"), ("域名", "網域"), ("默認", "預設"),
    ("當前", "目前"), ("支持", "支援"), ("響應", "回應"), ("連接", "連線"),
    ("進程", "程序"), ("程序", "程式"), ("官網", "官方網站"), ("打印", "列印"),
    ("回歸", "迴歸"), ("定時器", "排程器"), ("取舍", "取捨"),
)
_ZHTW_TRANSLATION = str.maketrans(ZHTW_FROM, ZHTW_TO)


def load_env(path: Path | None = None):
    """读项目根目录的 .env（已 gitignore）。已存在的环境变量优先，不覆盖。"""
    p = path or (ROOT / ".env")
    if not p.exists():
        return
    for line in p.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


load_env()

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 geo-skill/1.0"
)

# ---------------------------------------------------------------- 基础工具


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def slugify(text: str) -> str:
    text = re.sub(r"^https?://", "", (text or "").strip().lower())
    text = re.sub(r"[^a-z0-9一-鿿]+", "-", text).strip("-")
    return text[:48] or "project"


def die(msg: str, code: int = 1):
    print(f"[geo] 错误：{msg}", file=sys.stderr)
    sys.exit(code)


def info(msg: str):
    print(f"[geo] {msg}", file=sys.stderr)


def to_zh_tw(text: str) -> str:
    """將人類可讀文字轉成繁體中文（台灣用語）；英文與程式符號不受影響。"""
    out = str(text).translate(_ZHTW_TRANSLATION)
    for source, target in sorted(ZHTW_TERMS, key=lambda pair: len(pair[0]), reverse=True):
        out = out.replace(source, target)
    return out


def write_document(path: Path, text: str):
    """以 UTF-8 原子寫入繁體中文人類可讀文件。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(to_zh_tw(text), "utf-8")
    os.replace(tmp, p)


# ---------------------------------------------------------------- 项目目录

SLUG_OK = re.compile(r"^[a-z0-9一-鿿][a-z0-9一-鿿-]{0,47}$")


def project_dir(slug: str) -> Path:
    if not SLUG_OK.match(slug or ""):
        die(f"非法项目标识：{slug!r}")
    return WORK / slug


@contextmanager
def project_lock(slug: str):
    """项目级跨进程锁：load-modify-write 操作必须走它。"""
    d = project_dir(slug)
    d.mkdir(parents=True, exist_ok=True)
    with (d / ".lock").open("w") as fd:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)


def load_config(slug: str) -> dict:
    p = project_dir(slug) / "geo.json"
    if not p.exists():
        die(f"找不到项目配置 {p}，先运行：python3 scripts/geo.py init --url <网址>")
    return json.loads(p.read_text("utf-8"))


def save_config(slug: str, cfg: dict):
    """写配置前先备份。geo.json 里是一期的人工投入（问题库、竞品、口径），
    被误覆盖的代价远大于留几个备份文件。"""
    p = project_dir(slug) / "geo.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        bak = p.parent / ".geo.bak"
        bak.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        (bak / f"geo-{stamp}.json").write_text(p.read_text("utf-8"), "utf-8")
        old = sorted(bak.glob("geo-*.json"))
        for f in old[:-10]:
            f.unlink()
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, path)


def read_json(path: Path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text("utf-8"))
    except json.JSONDecodeError:
        info(f"警告：{p} 已损坏，使用默认值")
        return default


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_jsonl(path: Path):
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text("utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


# ---------------------------------------------------------------- HTTP

MAX_BYTES = 4_000_000  # 单页最多读 4MB，防止一头扎进安装包/大文件把管线拖死

# 一看就不是网页的路径，直接跳过（安装包、媒体、静态资源等）
SKIP_EXT = re.compile(
    r"\.(zip|gz|tgz|bz2|7z|rar|dmg|pkg|exe|msi|apk|ipa|deb|rpm|bin|iso"
    r"|mp4|mov|avi|mkv|mp3|wav|flac|png|jpe?g|gif|webp|svg|ico|bmp|tiff"
    r"|woff2?|ttf|eot|css|js|csv|xlsx?|docx?|pptx?|pdf)(\?|$)",
    re.I,
)
SKIP_PATH = re.compile(r"/(downloads?|dl|releases?|assets|static|cdn)/", re.I)


def is_fetchable(url: str) -> bool:
    if SKIP_EXT.search(url) or SKIP_PATH.search(url):
        return False
    tail = url.rstrip("/").rsplit("/", 1)[-1].lower()
    return tail not in {"download", "dl"}



def fetch(url: str, timeout: int = 12, retries: int = 1) -> dict:
    """返回 {url, final_url, status, html, elapsed, error}。只读网页，且有体积上限。"""
    if not is_fetchable(url):
        return {"url": url, "final_url": url, "status": 0, "html": "", "content_type": "",
                "elapsed": 0, "error": "跳过：不是网页（下载/媒体/静态资源）"}
    last = ""
    for attempt in range(retries + 1):
        try:
            t0 = time.time()
            r = requests.get(
                url,
                timeout=timeout,
                headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
                allow_redirects=True,
                stream=True,
            )
            # 5xx / 429 多是临时故障（服务端抖动、限流），值得按异常同样的节奏重试
            if (r.status_code >= 500 or r.status_code == 429) and attempt < retries:
                r.close()
                time.sleep(1.5)
                continue
            ctype = r.headers.get("Content-Type", "")
            if ctype and not any(k in ctype.lower() for k in ("html", "text/plain", "xml")):
                r.close()
                return {"url": url, "final_url": r.url, "status": r.status_code, "html": "",
                        "content_type": ctype, "elapsed": round(time.time() - t0, 2),
                        "error": f"跳过非网页内容（{ctype.split(';')[0]}）"}
            chunks, size = [], 0
            for chunk in r.iter_content(65536):
                chunks.append(chunk)
                size += len(chunk)
                if size >= MAX_BYTES:
                    break
            r.close()
            raw = b"".join(chunks)
            enc = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else None
            if not enc:
                m = re.search(rb'charset=["\']?([\w\-]+)', raw[:4000], re.I)
                enc = m.group(1).decode("ascii", "ignore") if m else "utf-8"
            return {
                "url": url,
                "final_url": r.url,
                "status": r.status_code,
                "html": raw.decode(enc, "replace"),
                "content_type": ctype,
                "elapsed": round(time.time() - t0, 2),
                "error": None,
            }
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            if attempt < retries:
                time.sleep(1.5)
    return {"url": url, "final_url": url, "status": 0, "html": "", "content_type": "", "elapsed": 0, "error": last}


def fetch_text(url: str, timeout: int = 8) -> str:
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": UA})
        if r.status_code == 200:
            r.encoding = r.apparent_encoding or r.encoding
            return r.text
    except Exception:  # noqa: BLE001
        pass
    return ""


def same_site(a: str, b: str) -> bool:
    ha, hb = urlparse(a).netloc.lower(), urlparse(b).netloc.lower()
    ha, hb = ha.removeprefix("www."), hb.removeprefix("www.")
    return ha == hb or ha.endswith("." + hb) or hb.endswith("." + ha)


# 跟踪参数：同一个页面挂不同参数会被当成多个 URL 重复抓，先剥掉
TRACKING_PARAMS = {"fbclid", "gclid", "dclid", "msclkid", "igshid", "mc_cid", "mc_eid",
                   "ref", "spm", "scm"}


def normalize_url(base: str, href: str) -> str | None:
    if not href:
        return None
    href = href.strip()
    if href.startswith(("mailto:", "tel:", "javascript:", "#")):
        return None
    u = urljoin(base, href)
    u, _, _ = u.partition("#")
    parts = urlparse(u)
    if parts.query:
        qs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
              if not (k.lower().startswith("utm_") or k.lower() in TRACKING_PARAMS)]
        u = urlunparse(parts._replace(query=urlencode(qs)))
    return u


# ---------------------------------------------------------------- 正文抽取

_DROP_TAGS = ["script", "style", "noscript", "svg", "iframe", "form", "template"]
_BOILER = re.compile(r"(nav|header|footer|sidebar|menu|breadcrumb|cookie|banner|advert)", re.I)


def parse_html(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", "lxml")


def main_text(soup: BeautifulSoup) -> str:
    # 恰好一个 <article> 才当正文容器；多个 <article>（列表页/分节页）时取 <main>
    # 整体，否则只保留第一节，数字/步骤/FAQ 全部丢失，正文评分被严重低估。
    articles = soup.find_all("article")
    body = (articles[0] if len(articles) == 1 else None) \
        or soup.find("main") or soup.body or soup
    clone = BeautifulSoup(str(body), "lxml")
    for t in clone(_DROP_TAGS):
        t.decompose()
    for t in clone.find_all(attrs={"class": _BOILER}):
        t.decompose()
    for t in clone.find_all(attrs={"id": _BOILER}):
        t.decompose()
    text = clone.get_text("\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text)


CJK = re.compile(r"[一-鿿]")
KANA = re.compile(r"[぀-ヿ]")


def cjk_ratio(text: str) -> float:
    """中文字符占「中文字符 + 英文单词」的比例，用来判断这页到底是中文页还是英文页。"""
    cjk = len(CJK.findall(text))
    latin = len(re.findall(r"[A-Za-z][A-Za-z'\-]*", text))
    total = cjk + latin
    return round(cjk / total, 3) if total else 0.0


def page_language(text: str, lang_attr: str = "") -> str:
    """返回 zh / ja / en / mixed / unknown。html lang 属性只作参考，正文说了算。"""
    if len(text) < 80:
        la = (lang_attr or "").lower()
        return ("zh" if la.startswith("zh") else "en" if la.startswith("en")
                else "ja" if la.startswith("ja") else "unknown")
    # 日文：假名够多且占（假名 + 汉字）比例明显，避免把引用了一两个日语词的中文页判成 ja
    kana = len(KANA.findall(text))
    if kana >= 5 and kana / (kana + len(CJK.findall(text))) > 0.2:
        return "ja"
    r = cjk_ratio(text)
    return "zh" if r >= 0.5 else "en" if r <= 0.1 else "mixed"


def word_count(text: str) -> int:
    """中英日混排统一折算成「词」：CJK 1.6 字算 1 词（接近中英信息密度比）。
    假名并入 CJK 统计：假名为主的日文页不算的话词数会被严重低估。"""
    cjk = len(CJK.findall(text)) + len(KANA.findall(text))
    latin = len(re.findall(r"[A-Za-z][A-Za-z'\-]*", text))
    return int(cjk / 1.6 + latin)


def jsonld(soup: BeautifulSoup) -> list:
    out = []
    for tag in soup.find_all("script", type=lambda v: v and "ld+json" in v):
        try:
            data = json.loads(tag.string or "{}")
        except Exception:  # noqa: BLE001
            continue
        out.extend(data if isinstance(data, list) else [data])
    return out


def jsonld_types(blocks: list) -> list[str]:
    types = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        t = b.get("@type")
        if isinstance(t, list):
            types.extend(str(x) for x in t)
        elif t:
            types.append(str(t))
        for sub in b.get("@graph", []) or []:
            if isinstance(sub, dict) and sub.get("@type"):
                st = sub["@type"]
                types.extend(st if isinstance(st, list) else [st])
    return sorted(set(types))
