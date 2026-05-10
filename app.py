import os
import sys
import uuid
import re
import subprocess
import time
import shutil
import traceback
from pathlib import Path
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import whisper
import zhconv
import jieba
import numpy as np
import librosa
import edge_tts
from pypinyin import pinyin, Style

# 启动时自动查找 ffmpeg 并加入 PATH（whisper 内部也需要调用 ffmpeg）
def _setup_ffmpeg_path():
    known_paths = [
        # winget 安装路径
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages",
        # 常见安装路径
        Path("C:/Program Files/ffmpeg/bin"),
        Path("C:/ffmpeg/bin"),
    ]
    # 先查找 winget 包目录
    winget_pkg = known_paths[0]
    if winget_pkg.exists():
        for d in winget_pkg.glob("Gyan.FFmpeg_*"):
            for ffmpeg_dir in d.glob("ffmpeg-*"):
                bin_dir = ffmpeg_dir / "bin"
                if (bin_dir / "ffmpeg.exe").exists():
                    os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
                    return str(bin_dir)
    # 再检查其他路径
    for p in known_paths[1:]:
        if (p / "ffmpeg.exe").exists():
            os.environ["PATH"] = str(p) + os.pathsep + os.environ.get("PATH", "")
            return str(p)
    # 最后尝试 PATH 中已有的
    if shutil.which("ffmpeg"):
        return shutil.which("ffmpeg")
    return None

_ffmpeg_path = _setup_ffmpeg_path()
if not _ffmpeg_path:
    print("警告：未找到 FFmpeg，音频提取和语音识别将无法工作！", file=sys.stderr)
else:
    print(f"FFmpeg 已找到: {_ffmpeg_path}", file=sys.stderr)

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = Path(__file__).parent / "uploads"
AUDIO_FOLDER = Path(__file__).parent / "audio"
UPLOAD_FOLDER.mkdir(exist_ok=True)
AUDIO_FOLDER.mkdir(exist_ok=True)

ALLOWED_VIDEO_EXTENSIONS = {"mp4", "avi", "mov", "mkv", "webm", "flv", "wmv", "m4v"}
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB

app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE

SUPPORTED_LANGUAGES = {
    "zh-CN": "中文（简体）",
    "zh-TW": "中文（繁体）",
    "en": "English",
    "ja": "日本語",
    "ko": "한국어",
    "fr": "Français",
    "de": "Deutsch",
    "es": "Español",
    "pt": "Português",
    "ru": "Русский",
    "ar": "العربية",
    "hi": "हिन्दी",
    "th": "ไทย",
    "vi": "Tiếng Việt",
    "it": "Italiano",
    "nl": "Nederlands",
    "tr": "Türkçe",
    "id": "Bahasa Indonesia",
}

# Whisper 语言代码 → SUPPORTED_LANGUAGES 映射
WHISPER_LANG_MAP = {
    "zh": "zh-CN",
    "en": "en",
    "ja": "ja",
    "ko": "ko",
    "fr": "fr",
    "de": "de",
    "es": "es",
    "pt": "pt",
    "ru": "ru",
    "ar": "ar",
    "hi": "hi",
    "th": "th",
    "vi": "vi",
    "it": "it",
    "nl": "nl",
    "tr": "tr",
    "id": "id",
}

# 语言代码到中文名称映射
LANG_NAMES = {
    "zh": "中文（普通话）",
    "en": "英语",
    "ja": "日语",
    "ko": "韩语",
    "fr": "法语",
    "de": "德语",
    "es": "西班牙语",
    "pt": "葡萄牙语",
    "ru": "俄语",
    "ar": "阿拉伯语",
    "hi": "印地语",
    "th": "泰语",
    "vi": "越南语",
    "it": "意大利语",
    "nl": "荷兰语",
    "tr": "土耳其语",
    "id": "印尼语",
}

# 常见中文错别字对照表（口语同音/近音混淆）
COMMON_TYPOS = {
    "在": "再", "的": "得", "地": "的", "做": "作",
    "象": "像", "侯": "候", "燥": "躁", "圆": "园",
    "副": "幅", "背": "备", "带": "戴", "课": "刻",
    "篮": "篮", "概": "慨", "账": "帐", "分": "份",
    "坐": "座", "蜜": "密", "拔": "拨", "历": "厉",
    "裸": "棵", "名": "各", "向": "像",
}

# ========== 语病检测规则 ==========

# 冗余表达模式：(冗余词组, 建议, 说明)
REDUNDANCY_PATTERNS = [
    ("非常很", "非常/很", "「非常」和「很」重复，语义啰嗦"),
    ("更加进一步", "进一步/更加", "「更加」和「进一步」语义重复"),
    ("目前当下", "目前/当下", "「目前」和「当下」重复"),
    ("首次第一次", "首次/第一次", "「首次」和「第一次」重复"),
    ("亲眼目睹", "亲眼看到/目睹", "「亲眼」和「目睹」语义重复，亲眼即目睹"),
    ("胜利凯旋", "凯旋", "凯旋即胜利归来，无需再加「胜利」"),
    ("彻底根除", "根除", "「彻底」和「根除」语义重复"),
    ("一致公认", "公认", "公认已含有一致之意"),
    ("免费赠送", "赠送", "赠送即为免费，无需再加「免费」"),
    ("大约左右", "大约/左右", "「大约」和「左右」语义重复，只保留一个"),
    ("大概左右", "大概/左右", "「大概」和「左右」语义重复，只保留一个"),
    ("可能也许", "可能/也许", "「可能」和「也许」语义重复"),
    ("立刻马上", "立刻/马上", "「立刻」和「马上」语义重复"),
    ("突然忽然", "突然/忽然", "「突然」和「忽然」语义重复"),
    ("全部都", "全部/都", "「全部」和「都」语义重复，只保留一个"),
    ("所有的都", "所有/都", "「所有」和「都」语义重复"),
    ("特别是尤其", "特别是/尤其是", "「特别是」和「尤其」语义重复"),
    ("目的是为了", "目的是/是为了", "「目的是」和「为了」语义重复"),
    ("因为由于", "因为/由于", "「因为」和「由于」语义重复"),
    ("但是却", "但是/却", "「但是」和「却」语义重复"),
    ("而且还", "而且/还", "「而且」和「还」语义重复"),
    ("不仅如此还", "不仅如此/还", "「不仅如此」和「还」语义重复"),
    ("更加越来越", "更加/越来越", "「更加」和「越来越」语义重复"),
    ("出乎意料之外", "出乎意料", "出乎意料已经包含了「之外」的意思"),
]

# 句式杂糅/语法错误模式：(正则, 错误说明, 建议)
GRAMMAR_PATTERNS = [
    (r"通过.+使", "「通过…使…」句式杂糅，缺乏主语", "删除「通过」或「使」"),
    (r"在.+下.+使", "「在…下，使…」句式杂糅，缺乏主语", "删除「使」或改用主动句"),
    (r"原因是.+造成的", "「原因是…造成的」句式杂糅", "改为「原因是…」或「是…造成的」"),
    (r"之所以.+的原因", "「之所以…的原因」语义重复", "改为「之所以…」或「…的原因是…」"),
    (r"是为了.+为目的", "「是为了…为目的」语义重复", "改为「是为了…」或「以…为目的」"),
    (r"由于.+因此", "「由于…因此」关联词搭配不当", "改为「由于…所以…」或「因为…因此…」"),
    (r"虽然.+但是也", "「虽然…但是也…」关联词多余", "改为「虽然…但是…」或保留一个关联词"),
    (r"不管.+都也", "关联词混杂", "保留一组关联词即可"),
    (r"不是.+而是也", "关联词使用不当", "保留「不是…而是…」即可"),
    (r"为了.+以便", "「为了…以便…」语义重复", "改为「为了…」或「…以便…」"),
]

# 标点符号检查
PUNCTUATION_RULES = [
    (r"[，,]{2,}", "连续使用逗号，建议使用句号分隔", "error"),
    (r"[。\.]{2,}", "连续句号，请检查是否误输入", "error"),
    (r"[！!]{2,}", "连续感叹号，建议只保留一个", "suggestion"),
    (r"[？?]{2,}", "连续问号，建议只保留一个", "suggestion"),
    (r"[,，]\s*[。\.]", "逗号后紧跟句号，可能是误输入", "error"),
    (r"[，,]\s*[，,]", "逗号冗余，请检查", "warning"),
]

# 常见搭配不当
COLLOCATION_ISSUES = [
    # (短语, 说明, 建议)
    ("提高了经验", "「提高」和「经验」搭配不当", "「积累了经验」或「提高了水平」"),
    ("降低了负担", "「降低」和「负担」搭配不当", "「减轻了负担」"),
    ("加强认识", "「加强」和「认识」搭配不当", "「加深认识」或「加强意识」"),
    ("达到水平", "「达到」和「水平」搭配不当", "「达到标准」或「提高水平」"),
    ("取得胜利", "搭配正确，如需确认可忽略", None),
]

# 待处理音频缓存: video_id -> {"audio_path": Path, "expires_at": float}
_pending = {}
# 重识别音频缓存: audio_stem -> {"audio_path": Path, "expires_at": float}
_audio_cache = {}

# 清理过期缓存（每调用时触发）
def _cleanup_expired():
    now = time.time()
    expired = [vid for vid, v in _pending.items() if v["expires_at"] < now]
    for vid in expired:
        item = _pending.pop(vid)
        item["audio_path"].unlink(missing_ok=True)
        item.get("video_path", Path()).unlink(missing_ok=True)
    # 清理过期音频缓存
    expired_audio = [k for k, v in _audio_cache.items() if v["expires_at"] < now]
    for k in expired_audio:
        item = _audio_cache.pop(k)
        item["audio_path"].unlink(missing_ok=True)

_model = None
_model_size = None


def get_whisper_model(model_size="small"):
    """获取 Whisper 模型，支持 base/small/medium"""
    global _model, _model_size
    # 如果已加载的模型与请求不同，释放旧模型重新加载
    if _model is not None and _model_size != model_size:
        import gc
        _model = None
        gc.collect()
    if _model is None:
        print(f"正在加载 Whisper 模型: {model_size}...", file=sys.stderr)
        _model = whisper.load_model(model_size)
        _model_size = model_size
        print(f"Whisper 模型 {model_size} 加载完成", file=sys.stderr)
    return _model


def allowed_video_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_VIDEO_EXTENSIONS


def extract_audio(video_path: Path, audio_path: Path):
    """提取音频并增强：高通滤波去低频噪声 + 轻量降噪 + 响度归一化"""
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-vn",
        "-af", "highpass=f=80,afftdn=nr=12:nf=-25,loudnorm=I=-16:TP=-1.5:LRA=11",
        "-acodec", "pcm_s16le",
        "-ar", "16000", "-ac", "1",
        "-y", str(audio_path),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return audio_path


def convert_to_simplified(text: str) -> str:
    """将繁体中文转为简体中文"""
    try:
        return zhconv.convert(text, "zh-cn")
    except Exception:
        return text


def detect_language_from_audio(audio_path: Path, model):
    audio = whisper.load_audio(str(audio_path))
    audio = whisper.pad_or_trim(audio)
    mel = whisper.log_mel_spectrogram(audio).to(model.device)
    _, probs = model.detect_language(mel)
    if not probs:
        return {}
    if isinstance(probs, list):
        return probs[0] if probs else {}
    return probs


@app.route("/")
def index():
    return render_template("index.html", languages=SUPPORTED_LANGUAGES)


@app.route("/api/languages")
def get_languages():
    return jsonify(SUPPORTED_LANGUAGES)


@app.route("/api/detect-language", methods=["POST"])
def detect_language():
    """步骤1：上传视频并检测语言"""
    _cleanup_expired()

    if "video" not in request.files:
        return jsonify({"error": "请选择视频文件"}), 400

    file = request.files["video"]
    if file.filename == "":
        return jsonify({"error": "请选择视频文件"}), 400

    if not allowed_video_file(file.filename):
        return jsonify({"error": f"不支持的视频格式，仅支持: {', '.join(ALLOWED_VIDEO_EXTENSIONS)}"}), 400

    ext = file.filename.rsplit(".", 1)[1].lower()
    video_id = str(uuid.uuid4())
    video_filename = f"{video_id}.{ext}"
    video_path = UPLOAD_FOLDER / video_filename
    file.save(str(video_path))

    try:
        audio_filename = f"{video_id}.wav"
        audio_path = AUDIO_FOLDER / audio_filename
        extract_audio(video_path, audio_path)

        model = get_whisper_model()
        lang_probs = detect_language_from_audio(audio_path, model)

        # 缓存音频，10 分钟后过期
        _pending[video_id] = {
            "audio_path": audio_path,
            "video_path": video_path,
            "expires_at": time.time() + 1800,
        }

        # 整理语言概率列表（按概率从高到低排序）
        sorted_langs = sorted(lang_probs.items(), key=lambda x: x[1], reverse=True)
        top_langs = []
        for code, prob in sorted_langs:
            top_langs.append({
                "code": code,
                "name": LANG_NAMES.get(code, code),
                "mapped_code": WHISPER_LANG_MAP.get(code),
                "probability": round(prob, 3),
            })

        top_lang = top_langs[0] if top_langs else {"code": "unknown", "name": "未知", "probability": 0}
        detected_info = {
            "whisper_code": top_lang["code"],
            "name": top_lang["name"],
            "mapped_code": top_lang.get("mapped_code"),
            "probability": top_lang["probability"],
        }

        return jsonify({
            "success": True,
            "video_id": video_id,
            "detected": detected_info,
            "all_languages": top_langs,
        })

    except subprocess.CalledProcessError:
        video_path.unlink(missing_ok=True)
        return jsonify({"error": "音频提取失败，请确保已安装 FFmpeg 并添加到系统 PATH"}), 500
    except Exception as e:
        video_path.unlink(missing_ok=True)
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": f"语言检测失败: {str(e)}"}), 500


# ========== 中文数字转阿拉伯数字 ==========
_CN_NUM_MAP = {
    "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    "百": 100, "千": 1000, "万": 10000, "亿": 100000000,
    "两": 2,
}
_CN_PLACE = {"十": 10, "百": 100, "千": 1000, "万": 10000, "亿": 100000000}


def _cn_num_to_int(cn_str):
    """将纯中文数字字符串转为整数，如 '三百零五' → 305"""
    if not cn_str:
        return None
    total = 0
    section = 0  # 万以下的节
    has_digit = False

    for i, ch in enumerate(cn_str):
        if ch in ("零",):
            has_digit = True
            continue
        if ch in _CN_PLACE:
            place = _CN_PLACE[ch]
            if section == 0:
                section = 1
            if place >= 10000:
                total = (total + section) * place
                section = 0
            else:
                section *= place
                total += section
                section = 0
            has_digit = True
        else:
            val = _CN_NUM_MAP.get(ch)
            if val is not None and val < 10:
                section = val
                has_digit = True

    total += section
    return total if has_digit else None


def convert_chinese_numerals(text):
    """将文本中的中文数字转换为阿拉伯数字"""
    # 匹配中文数字片段（连续中文数字字符）
    cn_digit_chars = "零一二三四五六七八九十百千万亿两"
    pattern = re.compile(rf"第?[{cn_digit_chars}]{{2,}}(?:点[{cn_digit_chars}]+)?(?:\.\d+)?")

    def replace_match(m):
        s = m.group()
        ordinal = s.startswith("第")
        if ordinal:
            s = s[1:]

        # 处理小数点
        decimal_part = ""
        if "点" in s:
            s, dec = s.split("点", 1)
            decimal_part = "."
            for ch in dec:
                val = _CN_NUM_MAP.get(ch)
                if val is not None and val < 10:
                    decimal_part += str(val)

        # 处理已有阿拉伯小数
        if "." in s:
            parts = s.split(".")
            int_str = parts[0]
            dec_str = parts[1] if len(parts) > 1 else ""
        else:
            int_str = s
            dec_str = ""

        result = _cn_num_to_int(int_str)
        if result is None:
            return m.group()

        if decimal_part or dec_str:
            result_str = str(result) + (decimal_part or ("." + dec_str))
        else:
            result_str = str(result)

        if ordinal:
            return "第" + result_str
        return result_str

    # 百分比模式
    pct_pattern = re.compile(r"百分之(["+ cn_digit_chars + r"]{2,})")
    text = pct_pattern.sub(lambda m: _pct_replace(m), text)

    # 通用中文数字
    text = pattern.sub(replace_match, text)

    return text


def _pct_replace(m):
    val = _cn_num_to_int(m.group(1))
    return f"{val}%" if val else m.group()


# ========== 智能标点恢复（增强版） ==========

# 句末语气词（句子结束信号）
SENTENCE_FINAL = {
    "了", "的", "吧", "吗", "呢", "啊", "呀", "哦", "哈", "嘛", "呗", "咯", "啦",
    "哇", "哟", "呐", "哎", "噢", "嘞", "哒", "噻", "嘛",
}

# 疑问标志词
QUESTION_MARKERS = {
    "什么", "怎么", "为什么", "哪", "谁", "何时", "多少", "吗", "呢", "咋",
    "干嘛", "如何", "是不是", "能不能", "要不要", "会不会", "可不可以",
    "怎么回事", "什么样", "怎么办", "哪个", "哪里", "哪位", "几点",
    "是否", "可否", "何必", "何不", "怎能", "岂能",
}

# 疑问句末词
QUESTION_END = {"吗", "呢", "吧", "呀"}

# 强烈感叹触发词
EXCLAMATION_STRONG = {
    "太", "真", "好", "多么", "这么", "那么", "非常", "特别", "极其",
    "实在", "简直", "绝对", "完全", "超级", "超",
    "天哪", "天啊", "老天", "厉害", "太棒了", "太好了", "太美了", "太强了",
    "竟然", "居然", "万万没想到", "不可思议", "难以置信",
    "不得了", "了不得",
}

# 感叹句末语气词
EXCLAMATION_END = {"啊", "呀", "哇", "啦", "哦", "哟", "哈", "呐", "哎", "唉", "噢"}

# 程度副词 + 感叹尾部模式
EXCLAMATION_DEGREE = {"太", "真", "好", "多么", "这么", "那么", "非常"}

# 连接词/转折词（前面加逗号）
COMMA_TRIGGERS = sorted([
    "但是", "不过", "然而", "所以", "因此", "而且", "并且", "或者", "还是",
    "然后", "接着", "另外", "此外", "同时", "于是", "可是", "只是",
    "总之", "换句话说", "例如", "比如", "也就是说",
    "首先", "其次", "最后", "第一", "第二", "第三",
    "一方面", "另一方面", "除此之外",
    "结果", "没想到", "忽然", "突然", "后来", "之后",
    "特别是", "尤其是", "包括", "比如说",
    "说实话", "说真的", "其实", "实际上", "事实上",
    "反正", "不管怎样", "无论如何",
    "反而", "反倒", "相反", "偏偏", "恰恰",
], key=len, reverse=True)

# 最小分句长度
MIN_CLAUSE_LEN = 4


def restore_punctuation(text, segments=None):
    """
    增强标点恢复：
    1. segment 时间间隔 + 语言规则分句
    2. 逐句判定句末标点（。？！）
    3. 句内插入逗号
    """
    if not text:
        return text

    clauses = _split_into_clauses(text, segments)

    result_parts = []
    for clause in clauses:
        clause = clause.strip()
        if not clause:
            continue
        punct = _classify_clause_punctuation(clause)
        result_parts.append(clause + punct)

    result = "".join(result_parts)

    # 句内逗号
    result = _insert_commas(result)

    # 清理异常组合
    result = _cleanup_punctuation(result)
    return result


def _split_into_clauses(text, segments):
    """分句：segment 时间间隔 + 语言边界词 + 长度阈值"""
    if not segments:
        return _split_by_rules(text)

    clauses = []
    current = ""
    prev_end = None

    boundary_words = ("然后", "所以", "但是", "不过", "而且", "另外", "接着", "之后", "于是", "结果")

    for seg in segments:
        seg_text = seg["text"].strip()
        if not seg_text:
            continue

        gap = 0
        if prev_end is not None:
            gap = seg["start"] - prev_end
        prev_end = seg["end"]

        # 信号1: 长停顿 (>1.2s) → 断句
        if gap > 1.2 and current:
            clauses.append(current)
            current = seg_text
            continue

        # 信号2: 中等停顿 (>0.5s) + 前句句末语气词 → 断句
        if gap > 0.5 and current and current[-1] in SENTENCE_FINAL:
            clauses.append(current)
            current = seg_text
            continue

        # 信号3: 段首是话题转换词 → 前句断句
        if current and any(seg_text.startswith(w) for w in boundary_words):
            clauses.append(current)
            current = seg_text
            continue

        # 信号4: 前句过长 (>30字) → 断句
        if len(current) >= 30:
            clauses.append(current)
            current = seg_text
            continue

        # 默认合并
        if current:
            current += seg_text
        else:
            current = seg_text

    if current:
        clauses.append(current)

    return clauses


def _split_by_rules(text):
    """无 segment 时的纯规则分句"""
    clauses = []
    current = ""
    boundary_words = ("然后", "所以", "但是", "不过", "而且", "接着", "于是", "结果", "后来")

    i = 0
    while i < len(text):
        current += text[i]

        # 句末语气词 + 长度够 → 倾向于断句
        if text[i] in SENTENCE_FINAL and len(current) >= MIN_CLAUSE_LEN:
            # 检查后面是否紧跟连接词（说明新句开始）
            for bw in boundary_words:
                if text[i+1:].startswith(bw):
                    clauses.append(current)
                    current = ""
                    break

        # 长度上限
        if len(current) >= 25:
            clauses.append(current)
            current = ""

        i += 1

    if current:
        clauses.append(current)

    return clauses


def _classify_clause_punctuation(clause):
    """判定句子标点类型：。 ？ ！"""
    clause = clause.rstrip("，。！？、；：\"'…，")

    if _is_question(clause):
        return "？"

    if _is_exclamation(clause):
        return "！"

    return "。"


def _is_question(clause):
    """判断是否为疑问句"""
    # 1. 句末疑问词（吗/呢）
    if clause and clause[-1] in QUESTION_END:
        return True

    # 2. 反问结构
    rhetorical = ("难道", "岂能", "怎能", "何不", "何必", "莫非", "难不成")
    for r in rhetorical:
        if r in clause:
            return True

    # 3. A不A 结构（"好不好" "行不行"）
    if re.search(r"(.)不\1", clause) or re.search(r"..不..", clause):
        for qw in ("吗", "呢", "呀", "吧"):
            if qw in clause:
                return True

    # 4. 疑问标志词 + 句末非陈述
    for q in QUESTION_MARKERS:
        idx = clause.find(q)
        if idx != -1 and len(clause) - idx < 15:
            # 排除间接引语
            indirect = ("知道", "忘记", "记得", "清楚", "明白", "了解", "告诉")
            prefix = clause[max(0, idx-2):idx]
            if not any(prefix.endswith(w) for w in indirect):
                return True

    return False


def _is_exclamation(clause):
    """判断是否为感叹句（评分制）"""
    score = 0

    # 1. 强烈感叹词
    for ew in EXCLAMATION_STRONG:
        if ew in clause:
            score += 2
            break

    # 2. 程度副词 + 了/啊/呀 结构（"太好了" "真美啊"）
    for deg in EXCLAMATION_DEGREE:
        idx = clause.find(deg)
        if idx != -1:
            rest = clause[idx + len(deg):]
            if any(rest.endswith(e) for e in EXCLAMATION_END) or "了" in rest[:5]:
                score += 3
                break

    # 3. 句末感叹语气词 + 短句
    if clause and clause[-1] in EXCLAMATION_END and len(clause) < 12:
        score += 1

    # 4. 叠词强调（"好好好" "对对对"）
    if re.search(r"(.)\1{2,}", clause):
        score += 1

    # 5. 惊叹词开头
    interjections = ("天哪", "天啊", "哇", "哎呀", "哎哟", "嘿", "哈哈", "啧啧")
    for inj in interjections:
        if clause.startswith(inj):
            score += 2
            break

    return score >= 3


def _insert_commas(text):
    """在连接词前 + 长篇中自然停顿点插入逗号"""
    # 1. 连接词前加逗号
    for trigger in COMMA_TRIGGERS:
        idx = 0
        tlen = len(trigger)
        while True:
            idx = text.find(trigger, idx)
            if idx == -1:
                break
            if idx > 0 and text[idx - 1] not in "，。！？、；：\n\"\"''…—":
                text = text[:idx] + "，" + text[idx:]
                idx += tlen + 1
            else:
                idx += tlen

    # 2. "是...的" 结构前后可加逗号分隔长句
    text = re.sub(r"(。)(\S{15,}是\S{5,}的)", r"\1\2", text)

    # 3. 逗号密度：长句 (>18字无标点) 在中间位置补逗号
    text = _ensure_comma_density(text)

    return text


def _ensure_comma_density(text):
    """确保长句有合理的逗号密度（约每12字一个停顿点）"""
    # 按句末标点拆分
    parts = re.split(r"([。！？\n])", text)
    result = []

    for i, part in enumerate(parts):
        if i % 2 == 1 or len(part) < 18:
            result.append(part)
            continue

        # 长句 (>18字) 且逗号太少 → 补逗号
        comma_count = part.count("，")
        expected_commas = max(0, len(part) // 14 - 1)
        if comma_count >= expected_commas:
            result.append(part)
            continue

        # 找合适插入点（优先在语气词、助词后）
        chars = list(part)
        insert_positions = []
        pause_chars = {"的", "了", "呢", "啊", "呀", "哦", "嘛", "吧", "啦", "后", "时", "中", "上", "下"}

        for j in range(6, len(chars) - 4):
            if chars[j] in pause_chars and chars[j-1] != "，" and chars[j+1] != "，":
                insert_positions.append(j)

        # 选最优插入点（均匀分布，避开已有逗号附近）
        selected = []
        needed = expected_commas - comma_count
        step = len(chars) // (needed + 1)

        for k in range(1, needed + 1):
            target_pos = k * step
            best = None
            best_dist = 999
            for pos in insert_positions:
                if pos in selected:
                    continue
                # 不能在已有逗号旁边的3字内
                too_close = False
                for ep in range(max(0, pos-3), min(len(chars), pos+4)):
                    if chars[ep] == "，":
                        too_close = True
                        break
                if too_close:
                    continue
                dist = abs(pos - target_pos)
                if dist < best_dist:
                    best_dist = dist
                    best = pos
            if best is not None:
                selected.append(best)

        # 从后往前插入（避免位置偏移）
        for pos in sorted(selected, reverse=True):
            chars.insert(pos + 1, "，")

        result.append("".join(chars))

    return "".join(result)


def _cleanup_punctuation(text):
    """清理异常标点组合"""
    text = re.sub(r"[，,]{2,}", "，", text)
    text = re.sub(r"[。\.]{2,}", "。", text)
    text = re.sub(r"[！!]{2,}", "！", text)
    text = re.sub(r"[？?]{2,}", "？", text)
    text = re.sub(r"[，,]\s*[。\.]", "。", text)
    text = re.sub(r"[，,]\s*[！!]", "！", text)
    text = re.sub(r"[，,]\s*[？?]", "？", text)
    text = re.sub(r"[，,]\s*[，,]", "，", text)
    text = re.sub(r"[。\.]\s*[！!]", "！", text)
    text = re.sub(r"[。\.]\s*[？?]", "？", text)
    text = re.sub(r"[？！!？]\s*[。\.]", lambda m: m.group()[0], text)
    return text


@app.route("/api/transcribe", methods=["POST"])
def transcribe_audio():
    """步骤2：使用指定语言进行语音转录"""
    _cleanup_expired()

    data = request.get_json()
    if not data:
        return jsonify({"error": "请求数据为空"}), 400

    video_id = data.get("video_id", "").strip()
    language = data.get("language", "").strip()
    if not video_id:
        return jsonify({"error": "缺少 video_id"}), 400

    item = _pending.get(video_id)
    if not item:
        return jsonify({"error": "会话已过期，请重新上传视频"}), 400

    audio_path = item["audio_path"]
    video_path = item.get("video_path")
    if not audio_path.exists():
        _pending.pop(video_id, None)
        return jsonify({"error": "音频文件已丢失，请重新上传"}), 400

    try:
        # 使用 small 模型（比 base 准确 40%+），支持 base/small/medium 切换
        model_size = data.get("model_size", "small")
        if model_size not in ("base", "small", "medium"):
            model_size = "small"
        model = get_whisper_model(model_size)

        transcribe_opts = {
            "beam_size": 5,
            "best_of": 3,
            "temperature": 0.0,
            "compression_ratio_threshold": 2.4,
            "logprob_threshold": -1.0,
            "no_speech_threshold": 0.6,
            "condition_on_previous_text": False,
            "fp16": False,
        }

        if language and language != "auto":
            # 将 mapped_code 反转为 whisper 的短代码
            whisper_lang = None
            for wcode, mcode in WHISPER_LANG_MAP.items():
                if mcode == language:
                    whisper_lang = wcode
                    break
            if whisper_lang:
                transcribe_opts["language"] = whisper_lang

        result = model.transcribe(str(audio_path), **transcribe_opts)

        segments = []
        for seg in result["segments"]:
            seg_text = seg["text"].strip()
            if not seg_text:
                continue
            if language == "zh-CN":
                seg_text = convert_to_simplified(seg_text)
            segments.append({
                "start": round(seg["start"], 2),
                "end": round(seg["end"], 2),
                "text": seg_text,
                "confidence": round(seg.get("avg_logprob", -1), 2),
                "no_speech_prob": round(seg.get("no_speech_prob", 0), 3),
                "compression_ratio": round(seg.get("compression_ratio", 0), 2),
            })

        transcribed_text = result["text"].strip()
        if language == "zh-CN":
            transcribed_text = convert_to_simplified(transcribed_text)

        # 智能标点恢复（中/日/韩语言）
        if language in ("zh-CN", "zh-TW", "ja", "ko"):
            transcribed_text = restore_punctuation(transcribed_text, segments)

        # 中文数字转阿拉伯数字
        if language in ("zh-CN", "zh-TW"):
            transcribed_text = convert_chinese_numerals(transcribed_text)

        detected_lang = result.get("language", "unknown")
        mapped_lang = WHISPER_LANG_MAP.get(detected_lang)

        return jsonify({
            "success": True,
            "text": transcribed_text,
            "whisper_language": detected_lang,
            "language": mapped_lang or detected_lang,
            "segments": segments,
            "model_size": model_size,
            "audio_stem": video_id,
        })

    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": f"语音识别失败: {str(e)}"}), 500
    finally:
        item = _pending.pop(video_id, None)
        if item:
            # 保留音频 10 分钟供重识别，视频立即删除
            _audio_cache[item["audio_path"].stem] = {
                "audio_path": item["audio_path"],
                "expires_at": time.time() + 600,
            }
            if item.get("video_path"):
                item["video_path"].unlink(missing_ok=True)


@app.route("/api/re-transcribe", methods=["POST"])
def re_transcribe_segment():
    """重识别低置信度片段，使用更高精度参数"""
    _cleanup_expired()
    data = request.get_json()
    if not data:
        return jsonify({"error": "请求数据为空"}), 400

    audio_stem = data.get("audio_stem", "").strip()
    start = data.get("start", 0)
    end = data.get("end", 0)
    language = data.get("language", "").strip()

    if not audio_stem:
        return jsonify({"error": "缺少 audio_stem"}), 400
    if end <= start:
        return jsonify({"error": "无效的时间范围"}), 400

    cache_entry = _audio_cache.get(audio_stem)
    if not cache_entry:
        return jsonify({"error": "音频已过期，请重新上传"}), 400

    audio_path = cache_entry["audio_path"]
    if not audio_path.exists():
        _audio_cache.pop(audio_stem, None)
        return jsonify({"error": "音频文件已丢失"}), 400

    try:
        # 加载音频并裁剪目标片段（前后各扩展 0.3s 缓冲）
        y, sr = librosa.load(str(audio_path), sr=16000, mono=True)
        margin = int(0.3 * sr)
        start_sample = max(0, int(start * sr) - margin)
        end_sample = min(len(y), int(end * sr) + margin)
        chunk = y[start_sample:end_sample]

        if len(chunk) < sr * 0.3:
            return jsonify({"error": "片段太短"}), 400

        # 保存临时音频
        import tempfile
        import soundfile as sf
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            sf.write(tmp.name, chunk, sr)
            tmp_path = tmp.name

        # 高精度重识别
        model = get_whisper_model("small")
        opts = {
            "beam_size": 15,
            "best_of": 10,
            "temperature": (0.0, 0.1, 0.2),
            "patience": 1.5,
            "compression_ratio_threshold": 2.4,
            "logprob_threshold": -1.0,
            "no_speech_threshold": 0.3,
            "condition_on_previous_text": False,
            "fp16": False,
        }
        if language and language != "auto":
            for wcode, mcode in WHISPER_LANG_MAP.items():
                if mcode == language:
                    opts["language"] = wcode
                    break

        result = model.transcribe(tmp_path, **opts)
        Path(tmp_path).unlink(missing_ok=True)

        text = result["text"].strip()
        if language == "zh-CN":
            text = convert_to_simplified(text)

        return jsonify({
            "success": True,
            "text": text,
            "segments": [{
                "start": seg["start"], "end": seg["end"],
                "text": seg["text"].strip(),
                "confidence": round(seg.get("avg_logprob", -1), 2),
            } for seg in result["segments"] if seg["text"].strip()],
        })

    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": f"重识别失败: {str(e)}"}), 500


@app.route("/api/tts", methods=["POST"])
def text_to_speech():
    """将翻译文本转为语音，使用目标语言的 TTS 声音"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "请求数据为空"}), 400

    text = data.get("text", "").strip()
    target_lang = data.get("target_lang", "en").strip()

    if not text:
        return jsonify({"error": "请输入要转换的文本"}), 400
    if len(text) > 2000:
        text = text[:2000]

    # 语言 → edge-tts 声音映射
    TTS_VOICES = {
        "en": "en-US-AriaNeural",
        "zh-CN": "zh-CN-XiaoxiaoNeural",
        "zh-TW": "zh-TW-HsiaoChenNeural",
        "ja": "ja-JP-NanamiNeural",
        "ko": "ko-KR-SunHiNeural",
        "fr": "fr-FR-DeniseNeural",
        "de": "de-DE-KatjaNeural",
        "es": "es-ES-ElviraNeural",
        "pt": "pt-BR-FranciscaNeural",
        "ru": "ru-RU-SvetlanaNeural",
        "ar": "ar-SA-ZariyahNeural",
        "hi": "hi-IN-SwaraNeural",
        "th": "th-TH-PremwadeeNeural",
        "vi": "vi-VN-HoaiMyNeural",
        "id": "id-ID-GadisNeural",
    }

    voice = TTS_VOICES.get(target_lang, "en-US-AriaNeural")

    try:
        import asyncio
        import tempfile

        async def _gen_tts():
            communicate = edge_tts.Communicate(text, voice)
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                await communicate.save(tmp.name)
                return tmp.name

        # 在已有 event loop 中运行
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, _gen_tts())
                tmp_path = future.result(timeout=60)
        else:
            tmp_path = asyncio.run(_gen_tts())

        # 读取为 base64
        import base64
        with open(tmp_path, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode()
        Path(tmp_path).unlink(missing_ok=True)

        return jsonify({
            "success": True,
            "audio_base64": audio_b64,
            "voice": voice,
            "format": "mp3",
        })

    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": f"TTS 生成失败: {str(e)}"}), 500


@app.route("/api/upload", methods=["POST"])
def upload_video():
    """一键上传并转录（兼容旧接口，内部走语言检测+转录）"""
    _cleanup_expired()

    if "video" not in request.files:
        return jsonify({"error": "请选择视频文件"}), 400

    file = request.files["video"]
    if file.filename == "":
        return jsonify({"error": "请选择视频文件"}), 400

    if not allowed_video_file(file.filename):
        return jsonify({"error": f"不支持的视频格式，仅支持: {', '.join(ALLOWED_VIDEO_EXTENSIONS)}"}), 400

    language = request.form.get("language", "").strip()

    ext = file.filename.rsplit(".", 1)[1].lower()
    video_id = str(uuid.uuid4())
    video_filename = f"{video_id}.{ext}"
    video_path = UPLOAD_FOLDER / video_filename
    file.save(str(video_path))

    try:
        audio_filename = f"{video_id}.wav"
        audio_path = AUDIO_FOLDER / audio_filename
        extract_audio(video_path, audio_path)

        model = get_whisper_model()

        transcribe_opts = {}
        whisper_lang = None
        if language and language != "auto":
            for wcode, mcode in WHISPER_LANG_MAP.items():
                if mcode == language:
                    whisper_lang = wcode
                    break
            if whisper_lang:
                transcribe_opts["language"] = whisper_lang

        result = model.transcribe(str(audio_path), **transcribe_opts)

        segments = []
        for seg in result["segments"]:
            seg_text = seg["text"].strip()
            if language == "zh-CN":
                seg_text = convert_to_simplified(seg_text)
            segments.append({
                "start": round(seg["start"], 2),
                "end": round(seg["end"], 2),
                "text": seg_text,
            })

        transcribed_text = result["text"].strip()
        if language == "zh-CN":
            transcribed_text = convert_to_simplified(transcribed_text)

        detected_lang = result.get("language", "unknown")

        return jsonify({
            "success": True,
            "text": transcribed_text,
            "whisper_language": detected_lang,
            "language": WHISPER_LANG_MAP.get(detected_lang, detected_lang),
            "segments": segments,
        })

    except subprocess.CalledProcessError:
        video_path.unlink(missing_ok=True)
        audio_path.unlink(missing_ok=True)
        return jsonify({"error": "音频提取失败，请确保已安装 FFmpeg 并添加到系统 PATH"}), 500
    except Exception as e:
        video_path.unlink(missing_ok=True)
        audio_path.unlink(missing_ok=True)
        return jsonify({"error": f"处理失败: {str(e)}"}), 500
    finally:
        video_path.unlink(missing_ok=True)
        audio_path.unlink(missing_ok=True)


@app.route("/api/proofread", methods=["POST"])
def proofread_text():
    """校对中文文本：错别字 + 语病 + 冗余 + 标点 + 搭配"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "请求数据为空"}), 400

    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "请输入要校对的文本"}), 400

    issues = []
    stats = {"error": 0, "warning": 0, "suggestion": 0}

    def get_char_context(pos, length=2):
        start = max(0, pos - length)
        end = min(len(text), pos + length + 1)
        return text[start:end]

    # ===== 一、错别字检测（逐词） =====
    words = list(jieba.tokenize(text))
    checked_positions = set()

    for word_info in words:
        word = word_info[0]
        start = word_info[1]
        end = word_info[2]

        if (start, end) in checked_positions:
            continue
        checked_positions.add((start, end))

        # 1a. 单字错别字
        if len(word) == 1 and word in COMMON_TYPOS:
            suggestion = COMMON_TYPOS[word]
            ctx = get_char_context(start, 2)
            issues.append({
                "start": start, "end": end,
                "original": word, "suggestion": suggestion,
                "context": ctx, "type": "typo", "severity": "warning",
                "reason": f"「{word}」在此处可能是「{suggestion}」的错别字",
            })
            stats["warning"] += 1

        # 1b. 多字词检查
        if len(word) >= 2 and len(word) <= 4:
            word_pinyin = pinyin(word, style=Style.TONE3)
            word_freq = jieba.get_FREQ(word)
            is_known_word = word_freq is not None

            typo_in_word = None
            for i, ch in enumerate(word):
                if ch in COMMON_TYPOS:
                    typo_in_word = (i, ch, COMMON_TYPOS[ch])
                    break

            if typo_in_word:
                idx, wrong, right = typo_in_word
                fixed_word = word[:idx] + right + word[idx+1:]
                fixed_freq = jieba.get_FREQ(fixed_word)
                if fixed_freq and fixed_freq > 5:
                    ctx = get_char_context(start, 3)
                    issues.append({
                        "start": start, "end": end,
                        "original": word, "suggestion": fixed_word,
                        "context": ctx, "type": "typo", "severity": "warning",
                        "reason": f"「{word}」中的「{wrong}」应为「{right}」，正确写法是「{fixed_word}」",
                    })
                    stats["warning"] += 1
                    continue

            if not is_known_word and not typo_in_word:
                candidates = _find_homophone_candidates(word, word_pinyin)
                if candidates:
                    ctx = get_char_context(start, 3)
                    issues.append({
                        "start": start, "end": end,
                        "original": word, "suggestion": candidates[0],
                        "alternatives": candidates[:3],
                        "context": ctx, "type": "unknown_word", "severity": "suggestion",
                        "reason": f"「{word}」不是常见词语，可能是「{candidates[0]}」的同音错误",
                    })
                    stats["suggestion"] += 1
                else:
                    ctx = get_char_context(start, 3)
                    issues.append({
                        "start": start, "end": end,
                        "original": word, "suggestion": None,
                        "context": ctx, "type": "unknown_word", "severity": "suggestion",
                        "reason": f"「{word}」不是常见词语，请检查是否应为其他词",
                    })
                    stats["suggestion"] += 1

    # ===== 二、冗余表达检测 =====
    for pattern, suggestion, desc in REDUNDANCY_PATTERNS:
        idx = text.find(pattern)
        if idx != -1:
            ctx = get_char_context(idx, 3)
            issues.append({
                "start": idx, "end": idx + len(pattern),
                "original": pattern, "suggestion": suggestion,
                "context": ctx, "type": "redundancy", "severity": "suggestion",
                "reason": desc,
            })
            stats["suggestion"] += 1

    # ===== 三、语法句式检测 =====
    for pat, desc, suggestion in GRAMMAR_PATTERNS:
        for m in re.finditer(pat, text):
            ctx = get_char_context(m.start(), 4)
            issues.append({
                "start": m.start(), "end": m.end(),
                "original": m.group(), "suggestion": suggestion,
                "context": ctx, "type": "grammar", "severity": "error",
                "reason": desc,
            })
            stats["error"] += 1

    # ===== 四、标点符号检测 =====
    for pat, desc, severity in PUNCTUATION_RULES:
        for m in re.finditer(pat, text):
            ctx = get_char_context(m.start(), 3)
            issues.append({
                "start": m.start(), "end": m.end(),
                "original": m.group(), "suggestion": "请检查标点使用",
                "context": ctx, "type": "punctuation", "severity": severity,
                "reason": desc,
            })
            stats[severity] += 1

    # ===== 五、常见搭配不当检测 =====
    for phrase, desc, suggestion in COLLOCATION_ISSUES:
        idx = text.find(phrase)
        if idx != -1:
            ctx = get_char_context(idx, 3)
            issues.append({
                "start": idx, "end": idx + len(phrase),
                "original": phrase, "suggestion": suggestion,
                "context": ctx, "type": "collocation", "severity": "warning",
                "reason": desc,
            })
            stats["warning"] += 1

    # 按位置排序
    issues.sort(key=lambda x: x["start"])

    return jsonify({
        "success": True,
        "issues": issues,
        "total": len(issues),
        "stats": stats,
        "summary": _generate_summary(stats),
    })


def _generate_summary(stats):
    """生成校对摘要信息"""
    total = stats["error"] + stats["warning"] + stats["suggestion"]
    if total == 0:
        return {"level": "clean", "text": "未发现明显问题，文本质量良好", "icon": "check"}
    if stats["error"] > 0:
        return {"level": "error", "text": f"发现 {stats['error']} 处语法错误、{stats['warning']} 处疑似错字、{stats['suggestion']} 处优化建议，建议修改后再使用", "icon": "alert"}
    if stats["warning"] > 0:
        return {"level": "warning", "text": f"发现 {stats['warning']} 处疑似错字、{stats['suggestion']} 处优化建议", "icon": "warning"}
    return {"level": "suggestion", "text": f"发现 {stats['suggestion']} 处优化建议，可根据需要调整", "icon": "info"}


def _find_homophone_candidates(word, word_pinyin):
    """根据拼音查找可能的正确词语"""
    candidates = []
    flat_py = "".join(p[0] for p in word_pinyin)
    # 在 jieba 词库中搜索同音词
    for test_word, freq in jieba.dt.FREQ.items():
        if len(test_word) == len(word):
            test_py = pinyin(test_word, style=Style.TONE3)
            test_flat = "".join(p[0] for p in test_py)
            if test_flat == flat_py and test_word != word:
                if freq > 10:
                    candidates.append((test_word, freq))
    candidates.sort(key=lambda x: x[1], reverse=True)
    return [c[0] for c in candidates[:5]]


@app.route("/api/translate", methods=["POST"])
def translate_text():
    data = request.get_json()
    if not data:
        return jsonify({"error": "请求数据为空"}), 400

    text = data.get("text", "").strip()
    source = data.get("source", "auto")
    target = data.get("target", "zh-CN")

    if not text:
        return jsonify({"error": "请输入要翻译的文本"}), 400

    if target not in SUPPORTED_LANGUAGES:
        return jsonify({"error": f"不支持的目标语言: {target}"}), 400

    try:
        import argostranslate.translate

        # 映射语言代码到 Argos 支持的代码
        LANG_MAP = {
            "zh-CN": "zh", "zh-TW": "zt", "en": "en", "ja": "ja",
            "ko": "ko", "fr": "fr", "de": "de", "es": "es",
            "ru": "ru", "pt": "pt", "ar": "ar", "hi": "hi",
            "th": "th", "vi": "vi", "id": "id", "it": "it",
            "nl": "nl", "pl": "pl", "sv": "sv", "tr": "tr",
        }
        from_code = LANG_MAP.get(source, "auto")
        to_code = LANG_MAP.get(target, "en")

        # Argos 不支持 auto，自动检测源语言
        if from_code == "auto":
            from_code = "zh" if any("一" <= c <= "鿿" for c in text) else "en"

        # 获取已安装的语言
        installed = argostranslate.translate.get_installed_languages()
        from_lang = next((l for l in installed if l.code == from_code), None)
        to_lang = next((l for l in installed if l.code == to_code), None)

        if not from_lang or not to_lang:
            # 回退到 MyMemory API
            import requests as req
            lang_pair = f"{from_code}|{to_code}" if from_code != "auto" else target
            resp = req.get(
                "https://api.mymemory.translated.net/get",
                params={"q": text, "langpair": lang_pair},
                timeout=15,
            )
            data = resp.json()
            result = data.get("responseData", {}).get("translatedText", "")
        else:
            translation = from_lang.get_translation(to_lang)
            result = translation.translate(text)

        if not result or result.strip() == text.strip():
            return jsonify({"error": "翻译失败，请稍后重试"}), 500

        return jsonify({
            "success": True,
            "translated_text": result,
            "source_lang": source,
            "target_lang": target,
        })

    except Exception as e:
        return jsonify({"error": f"翻译失败: {str(e)[:80]}"}), 500


@app.route("/favicon.ico")
def favicon():
    return "", 204


@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
