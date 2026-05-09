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
from pypinyin import pinyin, Style

# librosa 用于基频检测（男女声识别），可选依赖
try:
    import librosa
    HAS_LIBROSA = True
except ImportError:
    HAS_LIBROSA = False
    print("警告：librosa 未安装，男女声识别功能不可用", file=sys.stderr)

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

# ========== 行业/领域分类及其专业词库 ==========
DOMAIN_CATEGORIES = {
    "general": {
        "name": "通用日常",
        "icon": "💬",
        "desc": "日常对话、生活记录、Vlog、闲聊",
        "keywords": [
            "聊天", "对话", "日常", "生活", "朋友", "家庭", "工作", "学习",
            "吃饭", "睡觉", "上班", "下班", "周末", "假期", "旅游", "购物",
            "做饭", "打扫", "孩子", "父母", "聚会", "生日", "结婚", "搬家",
            "开车", "坐车", "走路", "天气", "衣服", "手机", "电脑", "电视",
        ],
    },
    "tech": {
        "name": "科技/互联网",
        "icon": "💻",
        "desc": "编程开发、AI人工智能、技术分享、产品发布",
        "keywords": [
            "人工智能", "机器学习", "深度学习", "算法", "模型", "训练", "推理",
            "神经网络", "自然语言处理", "计算机视觉", "大数据", "云计算", "服务器",
            "数据库", "API", "前端", "后端", "全栈", "Python", "Java", "JavaScript",
            "React", "Vue", "Docker", "Kubernetes", "微服务", "分布式", "高并发",
            "开源", "代码", "编程", "开发", "调试", "部署", "运维", "架构",
            "产品经理", "需求", "迭代", "敏捷", "Scrum", "SaaS", "PaaS", "IaaS",
            "区块链", "Web3", "元宇宙", "量子计算", "芯片", "GPU", "TPU", "向量",
        ],
    },
    "medical": {
        "name": "医疗/健康",
        "icon": "🏥",
        "desc": "医学讲座、健康科普、临床诊断、药物研究",
        "keywords": [
            "诊断", "治疗", "手术", "药物", "临床", "患者", "医生", "护士",
            "医院", "门诊", "住院", "检查", "化验", "CT", "核磁共振", "B超",
            "血压", "血糖", "血脂", "心电图", "疫苗", "抗体", "免疫", "感染",
            "抗生素", "激素", "麻醉", "输血", "急救", "ICU", "康复", "护理",
            "中医", "针灸", "推拿", "中药", "经络", "穴位", "辨证", "脉象",
            "肿瘤", "癌症", "糖尿病", "高血压", "心脏病", "脑卒中", "抑郁症",
            "基因", "细胞", "蛋白质", "酶", "代谢", "内分泌", "神经系统",
        ],
    },
    "legal": {
        "name": "法律/政务",
        "icon": "⚖️",
        "desc": "法律法规、政策解读、合同文书、庭审辩论",
        "keywords": [
            "法律", "法规", "法院", "法官", "律师", "原告", "被告", "诉讼",
            "合同", "协议", "证据", "判决", "裁决", "上诉", "仲裁", "调解",
            "刑法", "民法", "行政法", "宪法", "知识产权", "专利", "商标", "著作权",
            "合同纠纷", "侵权", "违约", "赔偿", "免责", "条款", "效力", "执行",
            "政策", "政府", "部门", "审批", "监管", "合规", "处罚", "复议",
            "立法", "司法", "执法", "检察院", "公安", "监察", "听证", "质证",
        ],
    },
    "finance": {
        "name": "金融/财经",
        "icon": "📈",
        "desc": "股票基金、经济分析、投资理财、商业评论",
        "keywords": [
            "股票", "基金", "债券", "期货", "外汇", "黄金", "原油", "数字货币",
            "投资", "理财", "风险", "收益", "利率", "汇率", "通胀", "GDP",
            "A股", "港股", "美股", "IPO", "上市", "并购", "重组", "退市",
            "牛市", "熊市", "涨停", "跌停", "成交量", "K线", "均线", "MACD",
            "银行", "保险", "证券", "信托", "私募", "公募", "PE", "VC",
            "市值", "估值", "市盈率", "市净率", "ROE", "财务报表", "资产负债表",
            "营收", "利润", "现金流", "分红", "股息", "回购", "拆股", "股权",
        ],
    },
    "education": {
        "name": "教育/学术",
        "icon": "🎓",
        "desc": "课程教学、学术讲座、论文答辩、考试辅导",
        "keywords": [
            "教育", "教学", "课程", "学生", "老师", "考试", "论文", "研究",
            "大学", "高中", "初中", "小学", "幼儿园", "博士", "硕士", "本科",
            "数学", "物理", "化学", "生物", "历史", "地理", "政治", "英语",
            "实验", "数据", "分析", "结论", "假设", "验证", "方法", "理论",
            "学术", "期刊", "发表", "引用", "参考文献", "导师", "答辩", "毕业",
            "高考", "中考", "考研", "考公", "雅思", "托福", "GRE", "SAT",
        ],
    },
    "entertainment": {
        "name": "影视/娱乐",
        "icon": "🎬",
        "desc": "电影电视剧、综艺节目、游戏直播、短视频",
        "keywords": [
            "电影", "电视剧", "综艺", "纪录片", "动画", "动漫", "短片", "预告片",
            "导演", "演员", "剧本", "镜头", "剪辑", "特效", "配音", "字幕",
            "票房", "收视率", "口碑", "评分", "影评", "剧透", "番剧", "追剧",
            "游戏", "电竞", "直播", "主播", "弹幕", "打赏", "通关", "BOSS",
            "角色", "剧情", "画面", "音效", "配乐", "摄影", "灯光", "美术",
            "综艺", "选秀", "真人秀", "脱口秀", "相声", "小品", "脱口秀大会",
        ],
    },
    "engineering": {
        "name": "工程/制造",
        "icon": "⚙️",
        "desc": "工业技术、建筑工程、机械制造、质量检测",
        "keywords": [
            "工程", "项目", "施工", "设计", "图纸", "材料", "设备", "工艺",
            "建筑", "桥梁", "隧道", "道路", "管道", "电气", "暖通", "给排水",
            "机械", "制造", "加工", "焊接", "铸造", "模具", "轴承", "齿轮",
            "质量", "检测", "标准", "认证", "ISO", "CE", "UL", "3C",
            "自动化", "PLC", "传感器", "变频器", "电机", "气缸", "液压", "气动",
            "CAD", "CAM", "CAE", "BIM", "有限元", "仿真", "拓扑优化", "逆向工程",
        ],
    },
    "food": {
        "name": "餐饮/美食",
        "icon": "🍳",
        "desc": "美食制作、餐饮评测、烹饪教程、饮食文化",
        "keywords": [
            "美食", "烹饪", "食材", "菜谱", "厨房", "餐厅", "厨师", "口味",
            "煎", "炒", "炸", "蒸", "煮", "烤", "炖", "焖", "烧", "卤",
            "牛肉", "猪肉", "鸡肉", "鱼肉", "虾", "蟹", "蔬菜", "水果",
            "酱油", "醋", "盐", "糖", "辣椒", "花椒", "葱", "姜", "蒜",
            "刀工", "火候", "调味", "摆盘", "色香味", "口感", "鲜嫩", "酥脆",
            "中餐", "西餐", "日料", "韩餐", "火锅", "烧烤", "甜品", "面点",
            "米其林", "大众点评", "网红店", "打卡", "探店", "外卖", "堂食",
        ],
    },
    "sports": {
        "name": "体育/电竞",
        "icon": "⚽",
        "desc": "赛事解说、运动教学、电竞比赛、健身训练",
        "keywords": [
            "比赛", "选手", "教练", "裁判", "冠军", "亚军", "季军", "奖牌",
            "奥运会", "世界杯", "锦标赛", "联赛", "季后赛", "总决赛", "预选赛",
            "足球", "篮球", "排球", "网球", "乒乓球", "羽毛球", "游泳", "田径",
            "进攻", "防守", "战术", "配合", "传球", "投篮", "射门", "得分",
            "LOL", "DOTA", "CS", "吃鸡", "王者荣耀", "原神", "电竞", "战队",
            "健身", "跑步", "瑜伽", "举重", "跳绳", "拉伸", "有氧", "无氧",
            "肌肉", "脂肪", "蛋白质", "碳水", "卡路里", "代谢", "增肌", "减脂",
            "马拉松", "铁人三项", "攀岩", "潜水", "滑雪", "冲浪", "滑板", "骑行",
        ],
    },
    "ecommerce": {
        "name": "电商/零售",
        "icon": "🛒",
        "desc": "电商运营、直播带货、供应链管理、零售营销",
        "keywords": [
            "电商", "淘宝", "京东", "拼多多", "抖音", "快手", "直播带货", "小红书",
            "GMV", "转化率", "客单价", "复购率", "流量", "点击率", "曝光", "ROI",
            "供应链", "仓储", "物流", "配送", "库存", "SKU", "SPU", "品类",
            "运营", "选品", "定价", "促销", "满减", "优惠券", "秒杀", "拼团",
            "买家", "卖家", "评价", "退货", "售后", "客服", "包邮", "自营",
            "跨境电商", "独立站", "Shopify", "亚马逊", "速卖通", "DTC", "私域", "公域",
        ],
    },
    "realestate": {
        "name": "房地产/建筑",
        "icon": "🏗️",
        "desc": "房地产开发、建筑设计、室内装修、物业管理",
        "keywords": [
            "房地产", "楼盘", "房价", "户型", "面积", "容积率", "绿化率", "公摊",
            "开发商", "置业顾问", "样板间", "毛坯", "精装", "别墅", "公寓", "商铺",
            "房贷", "首付", "利率", "公积金", "产权", "房产证", "契税", "过户",
            "建筑", "设计", "结构", "地基", "混凝土", "钢筋", "砌体", "幕墙",
            "装修", "硬装", "软装", "水电", "泥瓦", "油漆", "吊顶", "地板",
            "物业", "小区", "绿化", "停车位", "门禁", "电梯", "消防", "验收",
        ],
    },
    "automotive": {
        "name": "汽车/交通",
        "icon": "🚗",
        "desc": "汽车评测、智能驾驶、交通出行、新能源车",
        "keywords": [
            "汽车", "新能源", "电动车", "混动", "燃油车", "SUV", "MPV", "轿车",
            "比亚迪", "特斯拉", "蔚来", "小鹏", "理想", "华为", "小米汽车", "宁德时代",
            "智能驾驶", "自动驾驶", "激光雷达", "毫米波", "摄像头", "芯片", "算力", "OTA",
            "续航", "充电", "换电", "快充", "电池", "电机", "电控", "底盘",
            "发动机", "变速箱", "扭矩", "马力", "油耗", "排放", "国标", "碰撞测试",
            "交通", "交规", "驾照", "限行", "高速", "ETC", "导航", "停车",
        ],
    },
    "agriculture": {
        "name": "农业/养殖",
        "icon": "🌾",
        "desc": "农业种植、畜牧养殖、渔业水产、农业科技",
        "keywords": [
            "农业", "种植", "养殖", "畜牧", "渔业", "粮食", "蔬菜", "水果",
            "水稻", "小麦", "玉米", "大豆", "棉花", "油菜", "甘蔗", "茶叶",
            "养猪", "养鸡", "养牛", "养羊", "饲料", "兽药", "疫苗", "屠宰",
            "温室", "大棚", "灌溉", "施肥", "农药", "除草", "收割", "播种",
            "土壤", "气候", "病虫害", "产量", "品质", "有机", "绿色", "无公害",
            "智慧农业", "无人机", "卫星遥感", "物联网", "精准农业", "水肥一体", "育种", "转基因",
        ],
    },
    "tourism": {
        "name": "旅游/酒店",
        "icon": "✈️",
        "desc": "旅游攻略、酒店民宿、景点介绍、出行指南",
        "keywords": [
            "旅游", "旅行", "自由行", "跟团", "自驾游", "背包客", "穷游", "深度游",
            "景点", "景区", "门票", "导游", "攻略", "打卡", "网红", "小众",
            "酒店", "民宿", "青旅", "度假村", "温泉", "海边", "雪山", "古镇",
            "机票", "火车票", "签证", "护照", "免税店", "退税", "外币", "保险",
            "携程", "飞猪", "马蜂窝", "穷游网", "Booking", "Airbnb", "Agoda", "TripAdvisor",
            "国内游", "出境游", "周边游", "一日游", "邮轮", "露营", "徒步", "骑行",
        ],
    },
    "music_art": {
        "name": "音乐/艺术",
        "icon": "🎵",
        "desc": "音乐制作、乐器演奏、美术设计、艺术鉴赏",
        "keywords": [
            "音乐", "歌曲", "旋律", "和弦", "节奏", "编曲", "混音", "母带",
            "钢琴", "吉他", "贝斯", "鼓", "小提琴", "古筝", "二胡", "笛子",
            "流行", "摇滚", "民谣", "嘻哈", "电子", "古典", "爵士", "R&B",
            "演唱", "歌词", "创作", "翻唱", "乐队", "演出", "演唱会", "音乐节",
            "美术", "绘画", "油画", "国画", "素描", "水彩", "雕塑", "版画",
            "设计", "平面", "UI", "UX", "插画", "Logo", "海报", "字体",
            "艺术", "展览", "画廊", "拍卖", "收藏", "文物", "非遗", "传统文化",
        ],
    },
    "psychology": {
        "name": "心理/情感",
        "icon": "🧠",
        "desc": "心理咨询、情感关系、人格分析、心理健康",
        "keywords": [
            "心理", "情绪", "焦虑", "抑郁", "压力", "失眠", "强迫症", "社恐",
            "心理咨询", "治疗", "认知行为", "精神分析", "人本主义", "正念", "冥想", "催眠",
            "人格", "性格", "内向", "外向", "MBTI", "九型人格", "依恋类型", "安全感",
            "情感", "恋爱", "婚姻", "分手", "复合", "相亲", "暗恋", "表白",
            "原生家庭", "童年阴影", "自我成长", "边界感", "共情", "内耗", "PUA", "煤气灯",
            "亲密关系", "沟通", "冲突", "信任", "背叛", "修复", "陪伴", "倾听",
        ],
    },
    "beauty": {
        "name": "美容/时尚",
        "icon": "💄",
        "desc": "美妆护肤、时尚穿搭、发型设计、医美整形",
        "keywords": [
            "美妆", "护肤", "化妆", "粉底", "口红", "眼影", "腮红", "遮瑕",
            "防晒", "精华", "面霜", "面膜", "洁面", "爽肤水", "乳液", "眼霜",
            "干皮", "油皮", "混油", "敏感肌", "痘痘", "黑头", "毛孔", "美白",
            "穿搭", "时尚", "潮流", "复古", "简约", "日系", "韩系", "欧美风",
            "发型", "染发", "烫发", "剪发", "护发", "发膜", "精油", "假发",
            "医美", "整形", "双眼皮", "隆鼻", "瘦脸", "玻尿酸", "肉毒素", "热玛吉",
            "香水", "美甲", "纹身", "耳饰", "项链", "手链", "戒指", "包包",
        ],
    },
}

# 行业词库注入状态
_loaded_domain = None


def load_domain_keywords(domain):
    """将指定行业的专业词汇注入 jieba 词库"""
    global _loaded_domain
    if domain == _loaded_domain:
        return
    if domain not in DOMAIN_CATEGORIES:
        return

    # 清除之前的行业词（简单做法：重新加载默认词库并添加新词）
    keywords = DOMAIN_CATEGORIES[domain]["keywords"]
    for word in keywords:
        jieba.add_word(word, freq=100, tag="nz")
    _loaded_domain = domain

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

# 清理过期缓存（每调用时触发）
def _cleanup_expired():
    now = time.time()
    expired = [vid for vid, v in _pending.items() if v["expires_at"] < now]
    for vid in expired:
        item = _pending.pop(vid)
        item["audio_path"].unlink(missing_ok=True)
        item.get("video_path", Path()).unlink(missing_ok=True)

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


# ========== 智能标点恢复 ==========

# 中文句末标识词（通常后面应该加句号）
SENTENCE_FINAL_PARTICLES = {"了", "的", "呢", "吧", "吗", "啊", "呀", "哦", "哈", "嘛", "呗", "咯", "啦"}

# 疑问关键词 → 句末加问号
QUESTION_WORDS = {"什么", "怎么", "为什么", "哪", "谁", "何时", "多少", "吗", "呢", "咋", "干嘛", "如何", "是不是", "能不能", "要不要", "会不会"}

# 逗号插入连接词
COMMA_TRIGGERS = {"但是", "不过", "然而", "所以", "因此", "而且", "并且", "或者", "然后", "接着", "另外", "此外", "同时", "于是", "可是", "只是", "不过", "总之", "简而言之", "换句话说", "例如", "比如", "也就是说", "首先", "其次", "最后", "第一", "第二", "第三"}

# 分句最小长度（低于此长度不主动断句）
MIN_CLAUSE_LEN = 3


def restore_punctuation(text, segments=None):
    """基于规则 + segment 时间间隔恢复标点符号"""
    if not text:
        return text

    sentences = []
    current = ""
    prev_end = None

    # 有 segment 信息时，用时间间隔辅助断句
    if segments:
        for i, seg in enumerate(segments):
            seg_text = seg["text"].strip()
            if not seg_text:
                continue

            gap = 0
            if prev_end is not None:
                gap = seg["start"] - prev_end

            prev_end = seg["end"]

            # 间隔 > 1.0 秒 → 前一句加句号，新起一句
            if gap > 1.0 and current:
                current = _add_sentence_end_punct(current)
                sentences.append(current)
                current = seg_text
            # 间隔 > 0.4 秒 → 加逗号
            elif gap > 0.4 and current:
                current += "，" + seg_text
            else:
                if current:
                    current += seg_text
                else:
                    current = seg_text

        if current:
            current = _add_sentence_end_punct(current)
            sentences.append(current)
    else:
        # 无 segment 信息时，纯规则断句
        sentences = _rule_based_split(text)

    result = "".join(sentences)
    result = _insert_commas(result)
    result = _insert_question_marks(result)
    result = _cleanup_punctuation(result)
    return result


def _add_sentence_end_punct(s):
    """给句子末尾加合适的标点"""
    s = s.rstrip("，。！？、；：")
    if not s:
        return s
    last_char = s[-1]
    if last_char in "。！？":
        return s
    # 句末语气词后默认加句号
    return s + "。"


def _rule_based_split(text):
    """纯规则断句：按句子边界词 + 长度判断"""
    results = []
    current = ""
    for ch in text:
        current += ch
        if ch in SENTENCE_FINAL_PARTICLES and len(current) >= MIN_CLAUSE_LEN:
            # 语气词可能表示句子结束
            pass
        if len(current) >= 15:
            results.append(current)
            current = ""
    if current:
        results.append(current)
    return [_add_sentence_end_punct(s) for s in results]


def _insert_commas(text):
    """在连接词前插入逗号"""
    for trigger in sorted(COMMA_TRIGGERS, key=len, reverse=True):
        # 连接词前如果还没有标点，加逗号
        idx = 0
        while True:
            idx = text.find(trigger, idx)
            if idx == -1:
                break
            # 确保前面不是标点
            if idx > 0 and text[idx - 1] not in "，。！？、；：\n":
                text = text[:idx] + "，" + text[idx:]
                idx += len(trigger) + 1
            else:
                idx += len(trigger)
    return text


def _insert_question_marks(text):
    """检测疑问句并加问号"""
    for qword in sorted(QUESTION_WORDS, key=len, reverse=True):
        if qword in text:
            # 找该疑问词所在句子的句号，替换为问号
            idx = text.find(qword)
            sentence_end = text.find("。", idx)
            question_word = text.find("吗", idx)
            question_particle = text.find("呢", idx)
            candidates = [x for x in [sentence_end, question_word, question_particle] if x != -1]
            if candidates:
                end_pos = min(candidates)
                if end_pos == sentence_end:
                    text = text[:sentence_end] + "？" + text[sentence_end + 1:]
    return text


def _cleanup_punctuation(text):
    """清理异常标点组合"""
    text = re.sub(r"[，,]{2,}", "，", text)
    text = re.sub(r"[。\.]{2,}", "。", text)
    text = re.sub(r"[，,]\s*[。\.]", "。", text)
    text = re.sub(r"[，,]\s*[，,]", "，", text)
    return text


# ========== 男女声识别（大段聚类） ==========

# 基频相似度阈值：相邻段 f0 中位数相差在此范围内视为同一说话人
F0_SIMILARITY_THRESHOLD = 35  # Hz

# 性别判定阈值
MALE_F0_MAX = 165   # 低于此值为男性
FEMALE_F0_MIN = 180  # 高于此值为女性
# 165-180 之间为模糊区


def _extract_segment_f0(y, sr, seg):
    """提取单个片段的基频统计信息"""
    start_sample = int(seg["start"] * sr)
    end_sample = int(seg["end"] * sr)
    start_sample = max(0, start_sample)
    end_sample = min(len(y), end_sample)

    duration = seg["end"] - seg["start"]
    if duration < 0.5:  # 短于 0.5 秒跳过
        return None

    chunk = y[start_sample:end_sample]

    try:
        f0, voiced_flag, voiced_prob = librosa.pyin(
            chunk, fmin=50, fmax=500, sr=sr, fill_na=0,
        )
    except Exception:
        try:
            f0 = librosa.yin(chunk, fmin=50, fmax=500, sr=sr)
            voiced_prob = np.ones_like(f0)
        except Exception:
            return None

    voiced_f0 = f0[voiced_prob > 0.6]
    if len(voiced_f0) < 15:
        return None

    return {
        "median": float(np.median(voiced_f0)),
        "mean": float(np.mean(voiced_f0)),
        "std": float(np.std(voiced_f0)),
        "sample_count": len(voiced_f0),
    }


def detect_speaker_gender(audio_path, segments):
    """
    基于基频聚类的大段说话人识别：
    1. 提取每段 f0
    2. 按 f0 相似度合并相邻段 → 大段（对话轮次）
    3. 每个大段整体判定男女声
    """
    if not HAS_LIBROSA or not segments:
        return []

    try:
        y, sr = librosa.load(str(audio_path), sr=16000, mono=True)

        # 第一步：提取每段的 f0 特征
        f0_features = []
        for seg in segments:
            feat = _extract_segment_f0(y, sr, seg)
            f0_features.append(feat)

        # 第二步：按 f0 相似度合并相邻段为"说话块"
        blocks = []  # [(start_idx, end_idx, segments, f0s)]
        current_block = [0]
        current_f0s = [f0_features[0]["median"]] if f0_features[0] else []

        for i in range(1, len(segments)):
            prev_f0 = f0_features[i - 1]
            curr_f0 = f0_features[i]

            # 判断是否应该合并：前后段 f0 中位数接近
            should_merge = False
            if prev_f0 and curr_f0:
                diff = abs(prev_f0["median"] - curr_f0["median"])
                if diff < F0_SIMILARITY_THRESHOLD:
                    should_merge = True

            if should_merge:
                current_block.append(i)
                current_f0s.append(curr_f0["median"])
            else:
                blocks.append((current_block[0], current_block[-1], current_f0s))
                current_block = [i]
                current_f0s = [curr_f0["median"]] if curr_f0 else []

        if current_block:
            blocks.append((current_block[0], current_block[-1], current_f0s))

        # 第三步：合并太小的块到相邻大块
        blocks = _merge_small_blocks(blocks, segments)

        # 第四步：每个大块整体判定男女声
        results = []
        for start_i, end_i, block_f0s in blocks:
            if not block_f0s:
                gender = "unknown"
                confidence = 0.0
            else:
                block_median = float(np.median(block_f0s))
                gender, confidence = _classify_gender(block_median)

            # 大段的文本和时间
            block_text = "".join(segments[i]["text"] for i in range(start_i, end_i + 1))
            block_start = segments[start_i]["start"]
            block_end = segments[end_i]["end"]
            seg_count = end_i - start_i + 1

            results.append({
                "start": round(block_start, 2),
                "end": round(block_end, 2),
                "text": block_text,
                "gender": gender,
                "confidence": round(confidence, 2),
                "segment_count": seg_count,
                "duration": round(block_end - block_start, 1),
            })

        return results

    except Exception as e:
        print(f"性别检测失败: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return []


def _merge_small_blocks(blocks, segments):
    """把只有 1 个片段的孤立块合并到相邻更大的块"""
    if len(blocks) <= 1:
        return blocks

    merged = []
    i = 0
    while i < len(blocks):
        start_i, end_i, f0s = blocks[i]
        seg_count = end_i - start_i + 1

        if seg_count == 1 and i > 0 and i < len(blocks) - 1:
            # 孤立小段：合并到 f0 更接近的相邻块
            curr_f0 = f0s[0] if f0s else 0
            prev_f0s = blocks[i - 1][2]
            next_f0s = blocks[i + 1][2]

            prev_median = float(np.median(prev_f0s)) if prev_f0s else 0
            next_median = float(np.median(next_f0s)) if next_f0s else 0

            if prev_median and (not next_median or abs(curr_f0 - prev_median) <= abs(curr_f0 - next_median)):
                # 合并到前一个块
                prev_start, prev_end, prev_f0s_list = merged[-1]
                merged[-1] = (prev_start, end_i, prev_f0s_list + f0s)
            elif next_median:
                # 合并到后一个块（先跳过，下一轮处理）
                next_start, next_end_list, next_f0s_list = blocks[i + 1]
                blocks[i + 1] = (start_i, next_end_list, f0s + next_f0s_list)
            i += 1
            continue

        merged.append(blocks[i])
        i += 1

    return merged


def _classify_gender(median_f0):
    """根据基频中位数判定男女声，返回 (性别, 置信度)"""
    if median_f0 < MALE_F0_MAX:
        # 远离阈值越远置信度越高
        conf = min(0.95, 0.5 + (MALE_F0_MAX - median_f0) / 100)
        return "male", conf
    elif median_f0 > FEMALE_F0_MIN:
        conf = min(0.95, 0.5 + (median_f0 - FEMALE_F0_MIN) / 80)
        return "female", conf
    else:
        # 模糊区
        if median_f0 < 172:
            return "male", 0.55
        else:
            return "female", 0.55


def _build_initial_prompt(domain, language):
    """根据行业构建 initial_prompt，引导 Whisper 正确识别专业术语"""
    if domain not in DOMAIN_CATEGORIES:
        return ""
    keywords = DOMAIN_CATEGORIES[domain]["keywords"]

    # 取前 40 个词构建提示（太多了反而干扰）
    key_terms = keywords[:40]
    prompt_parts = []

    if language in ("zh-CN", "zh-TW"):
        prompt_parts.append("以下是关于" + DOMAIN_CATEGORIES[domain]["name"] + "领域的中文内容。")
        prompt_parts.append("涉及的专业词汇包括：" + "、".join(key_terms[:20]) + "等。")
        prompt_parts.append("请准确识别以上专业术语和行业词汇。")
    elif language == "en":
        prompt_parts.append("This is content about " + DOMAIN_CATEGORIES[domain]["name"] + ".")
        prompt_parts.append("Keywords include: " + ", ".join(key_terms[:20]) + ".")
    elif language == "ja":
        prompt_parts.append(DOMAIN_CATEGORIES[domain]["name"] + "に関する日本語の内容です。")

    return " ".join(prompt_parts)


@app.route("/api/domains")
def get_domains():
    """返回行业领域列表"""
    domains = []
    for code, info in DOMAIN_CATEGORIES.items():
        domains.append({
            "code": code,
            "name": info["name"],
            "icon": info["icon"],
            "desc": info["desc"],
            "keywords_count": len(info["keywords"]),
        })
    return jsonify({"success": True, "domains": domains})


@app.route("/api/transcribe", methods=["POST"])
def transcribe_audio():
    """步骤2：使用指定语言进行语音转录"""
    _cleanup_expired()

    data = request.get_json()
    if not data:
        return jsonify({"error": "请求数据为空"}), 400

    video_id = data.get("video_id", "").strip()
    language = data.get("language", "").strip()
    domain = data.get("domain", "general").strip()

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
        # 加载行业词库，提升 Whisper 识别准确率
        load_domain_keywords(domain)

        # 使用 small 模型（比 base 准确 40%+），支持 base/small/medium 切换
        model_size = data.get("model_size", "small")
        if model_size not in ("base", "small", "medium"):
            model_size = "small"
        model = get_whisper_model(model_size)

        # 构建行业提示词 initial_prompt，引导 Whisper 识别专业术语
        initial_prompt = _build_initial_prompt(domain, language)

        transcribe_opts = {
            "beam_size": 5,
            "temperature": 0.0,
            "compression_ratio_threshold": 2.4,
            "logprob_threshold": -1.0,
            "no_speech_threshold": 0.6,
            "condition_on_previous_text": False,
            "initial_prompt": initial_prompt,
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
            })

        transcribed_text = result["text"].strip()
        if language == "zh-CN":
            transcribed_text = convert_to_simplified(transcribed_text)

        # 智能标点恢复（中/日/韩语言）
        if language in ("zh-CN", "zh-TW", "ja", "ko"):
            transcribed_text = restore_punctuation(transcribed_text, segments)

        # 男女声识别（大段聚类）
        speaker_blocks = []
        if HAS_LIBROSA and segments:
            speaker_blocks = detect_speaker_gender(audio_path, segments)

        # 统计男女声比例
        male_blocks = [b for b in speaker_blocks if b["gender"] == "male"]
        female_blocks = [b for b in speaker_blocks if b["gender"] == "female"]
        male_duration = sum(b["duration"] for b in male_blocks)
        female_duration = sum(b["duration"] for b in female_blocks)
        speaker_stats = {
            "male_blocks": len(male_blocks),
            "female_blocks": len(female_blocks),
            "total_blocks": len(speaker_blocks),
            "male_duration": round(male_duration, 1),
            "female_duration": round(female_duration, 1),
            "has_detection": len(speaker_blocks) > 0,
        }

        detected_lang = result.get("language", "unknown")
        mapped_lang = WHISPER_LANG_MAP.get(detected_lang)

        return jsonify({
            "success": True,
            "text": transcribed_text,
            "whisper_language": detected_lang,
            "language": mapped_lang or detected_lang,
            "segments": segments,
            "speaker_blocks": speaker_blocks,
            "speaker_stats": speaker_stats,
            "domain": domain,
            "domain_name": DOMAIN_CATEGORIES.get(domain, {}).get("name", ""),
            "model_size": model_size,
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
