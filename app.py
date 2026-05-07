import os
import sys
import uuid
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
CONFUSABLE_PAIRS = {
    "在": "再", "的": "得", "得": "的", "地": "的",
    "做": "作", "作": "做", "已": "己", "哪": "那",
    "象": "像", "像": "象", "既": "即", "即": "既",
    "侯": "候", "燥": "躁", "躁": "燥", "练": "炼",
    "圆": "园", "园": "圆", "副": "幅", "幅": "副",
    "背": "备", "带": "戴", "课": "刻", "刻": "课",
    "蓝": "篮", "篮": "蓝", "概": "慨", "慨": "概",
    "账": "帐", "帐": "账", "长": "常", "常": "长",
    "分": "份", "份": "分", "坐": "座", "座": "坐",
    "蜜": "密", "密": "蜜", "买": "卖", "卖": "买",
    "拔": "拨", "拨": "拔", "历": "厉", "厉": "历",
    "已": "己", "己": "已", "未": "末", "末": "未",
    "人": "入", "入": "人", "天": "夫", "夫": "天",
    "土": "士", "士": "土", "午": "牛", "牛": "午",
    "真": "直", "直": "真", "名": "各", "各": "名",
    "干": "千", "千": "干", "目": "日", "日": "目",
    "向": "像", "内": "肉", "裸": "棵", "棵": "裸",
}
# 构建"错误→正确"方向的映射（以高频错字为 key）
COMMON_TYPOS = {
    "在": "再", "的": "得", "地": "的", "做": "作",
    "象": "像", "侯": "候", "燥": "躁", "圆": "园",
    "副": "幅", "背": "备", "带": "戴", "课": "刻",
    "篮": "篮", "概": "慨", "账": "帐", "分": "份",
    "坐": "座", "蜜": "密", "拔": "拨", "历": "厉",
    "裸": "棵", "名": "各", "向": "像",
}

# 待处理音频缓存: video_id -> {"audio_path": Path, "expires_at": float}
_pending = {}

# 清理过期缓存（每调用时触发）
def _cleanup_expired():
    now = time.time()
    expired = [vid for vid, v in _pending.items() if v["expires_at"] < now]
    for vid in expired:
        item = _pending.pop(vid)
        item["audio_path"].unlink(missing_ok=True)
        item.get("video_path", Path()).unlink(missing_ok=True)

_model = None


def get_whisper_model():
    global _model
    if _model is None:
        _model = whisper.load_model("base")
    return _model


def allowed_video_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_VIDEO_EXTENSIONS


def extract_audio(video_path: Path, audio_path: Path):
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le",
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
            "expires_at": time.time() + 600,
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
        model = get_whisper_model()

        # 如果指定了语言，直接传给 whisper 以提高识别精度
        transcribe_opts = {}
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
        mapped_lang = WHISPER_LANG_MAP.get(detected_lang)

        return jsonify({
            "success": True,
            "text": transcribed_text,
            "whisper_language": detected_lang,
            "language": mapped_lang or detected_lang,
            "segments": segments,
        })

    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": f"语音识别失败: {str(e)}"}), 500
    finally:
        item = _pending.pop(video_id, None)
        if item:
            item["audio_path"].unlink(missing_ok=True)
            if item.get("video_path"):
                item["video_path"].unlink(missing_ok=True)


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
    """校对中文文本，标注可能的错别字并给出修改建议"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "请求数据为空"}), 400

    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "请输入要校对的文本"}), 400

    issues = []
    # 1. jieba 分词 + 词性标注
    words = list(jieba.tokenize(text))
    # 2. 精确模式分词用于检测不成词片段
    seg_list = list(jieba.cut(text))

    # 构建位置辅助函数
    def get_char_context(pos, length=2):
        """获取某位置前后的字符上下文"""
        start = max(0, pos - length)
        end = min(len(text), pos + length + 1)
        return text[start:end]

    # 3. 逐词检查
    checked_positions = set()
    for word_info in words:
        word = word_info[0]
        start = word_info[1]
        end = word_info[2]

        # 跳过已检查的位置
        if (start, end) in checked_positions:
            continue
        checked_positions.add((start, end))

        # 3a. 检查常见错别字（单字在常见混淆表中）
        if len(word) == 1 and word in COMMON_TYPOS:
            suggestion = COMMON_TYPOS[word]
            ctx = get_char_context(start, 2)
            issues.append({
                "start": start,
                "end": end,
                "original": word,
                "suggestion": suggestion,
                "context": ctx,
                "type": "typo",
                "reason": f"「{word}」在此处可能是「{suggestion}」的错别字",
            })

        # 3b. 检查多字词是否为有效词语 或 包含混淆字
        if len(word) >= 2 and len(word) <= 4:
            word_pinyin = pinyin(word, style=Style.TONE3)
            word_freq = jieba.get_FREQ(word)
            is_known_word = word_freq is not None

            # 检查词中每个字是否在混淆表中
            typo_in_word = None
            for i, ch in enumerate(word):
                if ch in COMMON_TYPOS:
                    typo_in_word = (i, ch, COMMON_TYPOS[ch])
                    break

            if not is_known_word or typo_in_word:
                if typo_in_word:
                    # 替换混淆字后查词典
                    idx, wrong, right = typo_in_word
                    fixed_word = word[:idx] + right + word[idx+1:]
                    fixed_freq = jieba.get_FREQ(fixed_word)
                    if fixed_freq and fixed_freq > 5:
                        ctx = get_char_context(start, 3)
                        issues.append({
                            "start": start,
                            "end": end,
                            "original": word,
                            "suggestion": fixed_word,
                            "context": ctx,
                            "type": "typo",
                            "reason": f"「{word}」中的「{wrong}」应为「{right}」，正确写法是「{fixed_word}」",
                        })
                        continue

                if not is_known_word and not typo_in_word:
                    # 查找同音候选词
                    candidates = _find_homophone_candidates(word, word_pinyin)
                    if candidates:
                        ctx = get_char_context(start, 3)
                        issues.append({
                            "start": start,
                            "end": end,
                            "original": word,
                            "suggestion": candidates[0],
                            "alternatives": candidates[:3],
                            "context": ctx,
                            "type": "unknown_word",
                            "reason": f"「{word}」不是常见词语，可能是「{candidates[0]}」的同音错误",
                        })
                    else:
                        ctx = get_char_context(start, 3)
                        issues.append({
                            "start": start,
                            "end": end,
                            "original": word,
                            "suggestion": None,
                            "context": ctx,
                            "type": "unknown_word",
                            "reason": f"「{word}」不是常见词语，请检查是否应为其他词",
                        })

    return jsonify({
        "success": True,
        "issues": issues,
        "total": len(issues),
    })


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
        from deep_translator import GoogleTranslator
        translator = GoogleTranslator(source=source, target=target)
        result = translator.translate(text)

        return jsonify({
            "success": True,
            "translated_text": result,
            "source_lang": source,
            "target_lang": target,
        })

    except Exception as e:
        if len(text) > 5000:
            try:
                sentences = text.replace("\n", " ").split("。")
                translated_parts = []
                for sentence in sentences:
                    sentence = sentence.strip()
                    if sentence:
                        part = GoogleTranslator(source=source, target=target).translate(sentence)
                        translated_parts.append(part)
                result = "。".join(translated_parts)
                return jsonify({
                    "success": True,
                    "translated_text": result,
                    "source_lang": source,
                    "target_lang": target,
                })
            except Exception:
                pass

        return jsonify({"error": f"翻译失败: {str(e)}"}), 500


@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
