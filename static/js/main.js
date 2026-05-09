// ========== DOM 元素 ==========
const uploadArea = document.getElementById("uploadArea");
const videoInput = document.getElementById("videoInput");
const uploadProgress = document.getElementById("uploadProgress");
const progressText = document.getElementById("progressText");
const langDetectResult = document.getElementById("langDetectResult");
const detectedLangName = document.getElementById("detectedLangName");
const detectedConfidence = document.getElementById("detectedConfidence");
const manualLangSelect = document.getElementById("manualLangSelect");
const startTranscribeBtn = document.getElementById("startTranscribeBtn");
const transcribeProgress = document.getElementById("transcribeProgress");
const uploadInfo = document.getElementById("uploadInfo");
const fileName = document.getElementById("fileName");
const reUploadBtn = document.getElementById("reUploadBtn");

const sourceText = document.getElementById("sourceText");
const wordCount = document.getElementById("wordCount");
const proofreadBtn = document.getElementById("proofreadBtn");
const speakerSection = document.getElementById("speakerSection");
const speakerTimeline = document.getElementById("speakerTimeline");
const dismissSpeakerBtn = document.getElementById("dismissSpeakerBtn");
const proofreadPanel = document.getElementById("proofreadPanel");
const proofreadSummary = document.getElementById("proofreadSummary");
const proofreadList = document.getElementById("proofreadList");
const dismissProofreadBtn = document.getElementById("dismissProofreadBtn");
const copySourceBtn = document.getElementById("copySourceBtn");
const clearSourceBtn = document.getElementById("clearSourceBtn");

const sourceLang = document.getElementById("sourceLang");
const targetLang = document.getElementById("targetLang");
const swapLangBtn = document.getElementById("swapLangBtn");
const translateBtn = document.getElementById("translateBtn");

const resultArea = document.getElementById("resultArea");
const resultPlaceholder = document.getElementById("resultPlaceholder");
const resultContent = document.getElementById("resultContent");
const translateProgress = document.getElementById("translateProgress");
const copyResultBtn = document.getElementById("copyResultBtn");
const clearResultBtn = document.getElementById("clearResultBtn");

const domainGrid = document.getElementById("domainGrid");

const toast = document.getElementById("toast");

let currentVideoFile = null;
let currentVideoId = null;
let detectedLanguageCode = null;
let translatedText = "";
let currentDomain = "general";  // 默认通用日常

// ========== Toast 提示 ==========
let toastTimer;
function showToast(message, duration = 2500) {
    clearTimeout(toastTimer);
    toast.textContent = message;
    toast.classList.add("show");
    toastTimer = setTimeout(() => toast.classList.remove("show"), duration);
}

// ========== 行业领域选择 ==========
async function loadDomains() {
    try {
        const response = await fetch("/api/domains");
        const data = await response.json();
        if (data.success && data.domains) {
            renderDomainCards(data.domains);
        }
    } catch (error) {
        console.error("Failed to load domains:", error);
        domainGrid.innerHTML = '<div class="domain-card">加载失败，使用默认设置</div>';
    }
}

function renderDomainCards(domains) {
    domainGrid.innerHTML = "";
    domains.forEach(domain => {
        const card = document.createElement("div");
        card.className = `domain-card${domain.code === currentDomain ? " selected" : ""}`;
        card.dataset.code = domain.code;
        card.innerHTML = `
            <span class="domain-icon">${domain.icon}</span>
            <div class="domain-name">${domain.name}</div>
            <div class="domain-desc">${domain.desc}</div>
            <div class="domain-count">${domain.keywords_count} 个专业词汇</div>
        `;
        card.addEventListener("click", () => selectDomain(domain.code));
        domainGrid.appendChild(card);
    });
}

function selectDomain(code) {
    currentDomain = code;
    document.querySelectorAll(".domain-card").forEach(c => {
        c.classList.toggle("selected", c.dataset.code === code);
    });
    showToast(`已选择「${DOMAIN_NAMES[code] || code}」领域`);
}

// 域名映射（供选择时展示）
const DOMAIN_NAMES = {};
fetch("/api/domains").then(r => r.json()).then(data => {
    if (data.domains) data.domains.forEach(d => { DOMAIN_NAMES[d.code] = d.name; });
});

// ========== 行业选择折叠/展开 ==========
function collapseDomainSection() {
    const section = document.getElementById("domainSection");
    const toggleBtn = document.getElementById("domainToggleBtn");
    if (!section || section.classList.contains("collapsed")) return;

    section.style.maxHeight = section.scrollHeight + "px";
    requestAnimationFrame(() => {
        section.style.maxHeight = "0";
        section.style.opacity = "0";
        section.style.marginBottom = "0";
        section.style.overflow = "hidden";
    });
    section.classList.add("collapsed");

    // 显示展开按钮
    if (toggleBtn) toggleBtn.classList.remove("hidden");
}

function expandDomainSection() {
    const section = document.getElementById("domainSection");
    const toggleBtn = document.getElementById("domainToggleBtn");
    if (!section) return;

    section.classList.remove("collapsed", "hidden");
    section.style.maxHeight = section.scrollHeight + "px";
    section.style.opacity = "1";
    section.style.marginBottom = "16px";
    section.style.overflow = "visible";

    // 动画完成后清除固定高度
    section.addEventListener("transitionend", function handler() {
        section.style.maxHeight = "";
        section.removeEventListener("transitionend", handler);
    });

    // 隐藏展开按钮
    if (toggleBtn) toggleBtn.classList.add("hidden");
}

// 绑定展开按钮
document.getElementById("domainToggleBtn").addEventListener("click", expandDomainSection);

// 页面加载时加载域名
loadDomains();

// ========== 上传区域事件 ==========
uploadArea.addEventListener("click", () => videoInput.click());

uploadArea.addEventListener("dragover", (e) => {
    e.preventDefault();
    uploadArea.classList.add("dragover");
});

uploadArea.addEventListener("dragleave", () => {
    uploadArea.classList.remove("dragover");
});

uploadArea.addEventListener("drop", (e) => {
    e.preventDefault();
    uploadArea.classList.remove("dragover");
    const file = e.dataTransfer.files[0];
    if (file && file.type.startsWith("video/")) {
        handleVideoUpload(file);
    } else {
        showToast("请拖入视频文件");
    }
});

videoInput.addEventListener("change", () => {
    const file = videoInput.files[0];
    if (file) handleVideoUpload(file);
});

reUploadBtn.addEventListener("click", () => {
    if (sourceText.value.trim() || translatedText) {
        if (!confirm("确定重新上传吗？\n\n当前识别文本和翻译结果将被清空。")) return;
    }
    resetUpload();
    // 重新展开行业选择
    expandDomainSection();
});

// ========== 视频上传处理 ==========
function resetUpload() {
    currentVideoFile = null;
    currentVideoId = null;
    detectedLanguageCode = null;
    videoInput.value = "";
    uploadArea.classList.remove("hidden");
    uploadProgress.classList.add("hidden");
    langDetectResult.classList.add("hidden");
    transcribeProgress.classList.add("hidden");
    uploadInfo.classList.add("hidden");
    manualLangSelect.value = "";
    sourceText.value = "";
    sourceText.disabled = true;
    sourceLang.disabled = true;
    translateBtn.disabled = true;
    proofreadBtn.disabled = true;
    proofreadPanel.classList.add("hidden");
    speakerSection.classList.add("hidden");
    updateWordCount();
    clearResult();
}

// 步骤1：上传视频 → 检测语言
async function handleVideoUpload(file) {
    if (file.size > 500 * 1024 * 1024) {
        showToast("文件大小不能超过 500MB");
        return;
    }

    currentVideoFile = file;

    uploadArea.classList.add("hidden");
    uploadProgress.classList.remove("hidden");
    progressText.textContent = "正在上传视频并检测语言...";

    const formData = new FormData();
    formData.append("video", file);

    try {
        const response = await fetch("/api/detect-language", {
            method: "POST",
            body: formData,
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "语言检测失败");
        }

        currentVideoId = data.video_id;
        detectedLanguageCode = data.detected.mapped_code;

        // 隐藏上传进度，显示语言检测结果
        uploadProgress.classList.add("hidden");
        langDetectResult.classList.remove("hidden");

        const probPercent = Math.round(data.detected.probability * 100);
        detectedLangName.textContent = data.detected.name;
        detectedConfidence.textContent = "置信度 " + probPercent + "%";

        // 设置语言选择器默认值
        if (data.detected.mapped_code) {
            for (const opt of manualLangSelect.options) {
                if (opt.value === data.detected.mapped_code) {
                    opt.selected = true;
                    break;
                }
            }
        }

        // 自动设置翻译源语言
        if (data.detected.mapped_code) {
            sourceLang.value = data.detected.mapped_code;
        }

    } catch (error) {
        uploadProgress.classList.add("hidden");
        uploadArea.classList.remove("hidden");
        showToast(`语言检测失败: ${error.message}`);
        console.error("Detect error:", error);
    }
}

// 步骤2：确认语言 → 开始转录
startTranscribeBtn.addEventListener("click", async () => {
    if (!currentVideoId) {
        showToast("请先上传视频");
        return;
    }

    // 用户手动选择的语言优先，否则用检测到的语言
    let language = manualLangSelect.value || detectedLanguageCode || "auto";

    langDetectResult.classList.add("hidden");
    transcribeProgress.classList.remove("hidden");

    try {
        const response = await fetch("/api/transcribe", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                video_id: currentVideoId,
                language: language,
                domain: currentDomain,
                model_size: "small",
            }),
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "语音识别失败");
        }

        // 显示转录结果
        sourceText.value = data.text;
        sourceText.disabled = false;
        sourceLang.disabled = false;
        translateBtn.disabled = false;
        proofreadBtn.disabled = false;
        updateWordCount();

        // 更新上传状态
        transcribeProgress.classList.add("hidden");
        uploadInfo.classList.remove("hidden");
        fileName.textContent = currentVideoFile ? currentVideoFile.name : "视频";

        // 同步检测到的语言到翻译源语言
        if (data.language && data.language !== "unknown") {
            const mapped = data.language;
            if (sourceLang.querySelector(`option[value="${mapped}"]`)) {
                sourceLang.value = mapped;
            }
        }

        showToast(`识别完成！共 ${data.text.length} 个字符，模型: ${data.model_size || 'small'}`);

        // 折叠行业选择（可重新展开）
        collapseDomainSection();

        // 渲染说话人标注（大段）
        if (data.speaker_stats && data.speaker_stats.has_detection) {
            renderSpeakerTimeline(data.speaker_blocks, data.speaker_stats);
        }

        // 自动触发校对
        setTimeout(() => performProofread(true), 300);

    } catch (error) {
        transcribeProgress.classList.add("hidden");
        langDetectResult.classList.remove("hidden");
        showToast(`语音识别失败: ${error.message}`);
        console.error("Transcribe error:", error);
    }
});

// ========== 文本校对 ==========
proofreadBtn.addEventListener("click", () => performProofread(false));

async function performProofread(isAuto) {
    const text = sourceText.value.trim();
    if (!text) {
        if (!isAuto) showToast("请先输入或识别文本");
        return;
    }

    if (!isAuto) {
        proofreadBtn.disabled = true;
        proofreadBtn.textContent = "校对中...";
    }
    proofreadPanel.classList.add("hidden");
    // 隐藏旧提醒框
    const oldBanner = document.querySelector(".alert-banner");
    if (oldBanner) oldBanner.remove();
    const oldIndicator = document.querySelector(".auto-proofread-indicator");
    if (oldIndicator) oldIndicator.remove();

    // 自动校对的加载提示
    if (isAuto && data.issues === undefined) {
        const indicator = document.createElement("div");
        indicator.className = "auto-proofread-indicator";
        indicator.innerHTML = '<div class="spinner spinner-sm"></div><span>智能校对中...</span>';
        proofreadPanel.parentNode.insertBefore(indicator, proofreadPanel);
    }

    try {
        const response = await fetch("/api/proofread", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text }),
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "校对失败");
        }

        // 移除加载指示器
        const indicator = document.querySelector(".auto-proofread-indicator");
        if (indicator) indicator.remove();

        // 显示提醒框
        showAlertBanner(data);

        // 渲染详细列表
        renderProofreadResults(data);

    } catch (error) {
        const indicator = document.querySelector(".auto-proofread-indicator");
        if (indicator) indicator.remove();
        if (!isAuto) {
            showToast(`校对失败: ${error.message}`);
            console.error("Proofread error:", error);
        }
    } finally {
        proofreadBtn.disabled = false;
        proofreadBtn.textContent = "🔍 校对";
    }
}

// ========== 醒目的提醒框 ==========
function showAlertBanner(data) {
    const summary = data.summary;
    const stats = data.stats;

    let iconSymbol = "";
    let titleText = "";
    if (summary.level === "clean") {
        iconSymbol = "✅";
        titleText = "文本检查通过";
    } else if (summary.level === "error") {
        iconSymbol = "🚫";
        titleText = "发现语法错误，建议修改";
    } else if (summary.level === "warning") {
        iconSymbol = "⚠️";
        titleText = "发现疑似问题，请关注";
    } else {
        iconSymbol = "💡";
        titleText = "优化建议";
    }

    const banner = document.createElement("div");
    banner.className = `alert-banner ${summary.level}`;
    banner.id = "alertBanner";

    let statsHTML = "";
    if (stats.error > 0) {
        statsHTML += `<div class="alert-stat num-error">❌ ${stats.error} 错误</div>`;
    }
    if (stats.warning > 0) {
        statsHTML += `<div class="alert-stat num-warning">⚠️ ${stats.warning} 警告</div>`;
    }
    if (stats.suggestion > 0) {
        statsHTML += `<div class="alert-stat num-suggestion">💡 ${stats.suggestion} 建议</div>`;
    }

    banner.innerHTML = `
        <div class="alert-icon">${iconSymbol}</div>
        <div class="alert-body">
            <div class="alert-title">${titleText}</div>
            <div class="alert-desc">${summary.text}</div>
        </div>
        ${statsHTML ? `<div class="alert-stats">${statsHTML}</div>` : ""}
        <button class="alert-close" id="dismissAlertBtn" title="关闭提醒">×</button>
    `;

    // 插入到编辑区顶部
    const editorSection = document.querySelector(".editor-section");
    const sectionHeader = editorSection.querySelector(".section-header");
    sectionHeader.after(banner);

    // 关闭按钮
    document.getElementById("dismissAlertBtn").addEventListener("click", () => {
        banner.style.animation = "fadeOut 0.2s ease forwards";
        setTimeout(() => banner.remove(), 200);
    });
}

function renderProofreadResults(data) {
    proofreadList.innerHTML = "";

    if (!data.issues || data.issues.length === 0) {
        proofreadSummary.textContent = "✅ 未发现明显问题";
        proofreadPanel.classList.remove("hidden");
        const emptyItem = document.createElement("div");
        emptyItem.className = "proofread-item";
        emptyItem.innerHTML = '<span style="color: var(--text-secondary); font-size: 13px;">✅ 文本看起来没问题，无需修改。</span>';
        proofreadList.appendChild(emptyItem);
        return;
    }

    proofreadSummary.textContent = `🔍 发现 ${data.total} 处问题（点击可定位到原文）`;

    data.issues.forEach((issue, index) => {
        const item = document.createElement("div");
        item.className = "proofread-item clickable";
        item.id = `proofread-issue-${index}`;
        item.title = "点击定位到原文中的问题位置";

        // 类型徽章
        const typeLabels = {
            typo: "错字", unknown_word: "疑词", redundancy: "冗余",
            grammar: "语法", punctuation: "标点", collocation: "搭配",
        };
        const badgeLabel = typeLabels[issue.type] || issue.type;
        const badgeClass = issue.type;

        // 严重程度圆点
        let severityDot = "";
        if (issue.severity) {
            severityDot = `<span class="severity-dot severity-${issue.severity}" title="${issue.severity}"></span>`;
        }

        let suggestionHTML = "";
        if (issue.suggestion) {
            suggestionHTML = `<span class="issue-suggestion" title="点击替换">→ ${issue.suggestion}</span>`;
        }

        let altHTML = "";
        if (issue.alternatives && issue.alternatives.length > 1) {
            altHTML = `<div style="font-size:11px;color:var(--text-muted);margin-top:2px">其他可能: ${issue.alternatives.slice(1).join(" / ")}</div>`;
        }

        let actionHTML = "";
        if (issue.suggestion && issue.suggestion !== "请检查标点使用" && issue.type !== "grammar") {
            actionHTML = `
                <button class="issue-action accept" data-index="${index}">替换</button>
                <button class="issue-action ignore" data-index="${index}">忽略</button>
            `;
        } else if (issue.type === "grammar" || issue.type === "punctuation") {
            actionHTML = `<button class="issue-action ignore" data-index="${index}">忽略</button>`;
        }

        // 定位图标
        const locateIcon = `<span style="flex-shrink:0;font-size:14px;color:var(--text-muted);margin-left:4px" title="点击定位">📍</span>`;

        item.innerHTML = `
            ${severityDot}
            <span class="issue-badge ${badgeClass}">${badgeLabel}</span>
            <div class="issue-info">
                <span class="issue-text">「${issue.original}」</span>
                ${suggestionHTML}
                <div class="issue-reason">${issue.reason}</div>
                <div style="font-size:11px;color:var(--text-muted);margin-top:1px">上下文: ...${issue.context}...</div>
                ${altHTML}
            </div>
            ${locateIcon}
            <div style="display:flex;gap:6px;flex-shrink:0">
                ${actionHTML}
            </div>
        `;

        // 整行点击 → 定位到原文
        item.addEventListener("click", (e) => {
            // 不拦截按钮自身的点击
            if (e.target.tagName === "BUTTON" || e.target.closest(".issue-suggestion")) return;
            locateIssueInText(issue, index);
        });

        proofreadList.appendChild(item);
    });

    proofreadPanel.classList.remove("hidden");

    // 绑定替换按钮事件
    proofreadList.querySelectorAll(".issue-action.accept").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const idx = parseInt(btn.dataset.index);
            const issue = data.issues[idx];
            if (issue.suggestion) {
                const before = sourceText.value.substring(0, issue.start);
                const after = sourceText.value.substring(issue.end);
                sourceText.value = before + issue.suggestion + after;
                updateWordCount();
                const itemEl = document.getElementById(`proofread-issue-${idx}`);
                if (itemEl) itemEl.style.opacity = "0.4";
                btn.disabled = true;
                btn.textContent = "已替换";
                showToast("已替换");
            }
        });
    });

    // 绑定忽略按钮事件
    proofreadList.querySelectorAll(".issue-action.ignore").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const idx = parseInt(btn.dataset.index);
            const itemEl = document.getElementById(`proofread-issue-${idx}`);
            if (itemEl) itemEl.style.opacity = "0.4";
            btn.disabled = true;
            btn.textContent = "已忽略";
        });
    });

    // suggestion 点击 → 替换
    proofreadList.querySelectorAll(".issue-suggestion").forEach(sug => {
        sug.addEventListener("click", (e) => {
            e.stopPropagation();
            const itemEl = sug.closest(".proofread-item");
            const acceptBtn = itemEl.querySelector(".issue-action.accept");
            if (acceptBtn) acceptBtn.click();
        });
    });
}

// ========== 定位到原文问题位置 ==========
function locateIssueInText(issue, index) {
    sourceText.focus();

    // 选中问题文本
    sourceText.setSelectionRange(issue.start, issue.end);

    // 计算行高，滚动到可见区域
    const textarea = sourceText;
    const textBefore = textarea.value.substring(0, issue.start);
    const lineHeight = parseFloat(getComputedStyle(textarea).lineHeight) || 22;
    const paddingTop = parseFloat(getComputedStyle(textarea).paddingTop) || 16;
    const lines = textBefore.split("\n").length;
    const targetScroll = (lines - 1) * lineHeight + paddingTop - 60; // 60px 偏移，避免太贴顶
    textarea.scrollTop = Math.max(0, targetScroll);

    // 添加脉冲高亮动画
    textarea.classList.remove("highlight-pulse");
    void textarea.offsetWidth; // 强制回流
    textarea.classList.add("highlight-pulse");

    // 当前点击的条目高亮
    const allItems = proofreadList.querySelectorAll(".proofread-item.clickable");
    allItems.forEach(el => el.style.background = "");
    const currentItem = document.getElementById(`proofread-issue-${index}`);
    if (currentItem) {
        currentItem.style.background = "#fde68a";
        setTimeout(() => { currentItem.style.background = ""; }, 2000);
    }
}

dismissProofreadBtn.addEventListener("click", () => {
    proofreadPanel.classList.add("hidden");
});

// ========== 说话人标注 ==========
function renderSpeakerTimeline(blocks, stats) {
    speakerTimeline.innerHTML = "";

    if (!blocks || blocks.length === 0) return;

    blocks.forEach((block, i) => {
        const gender = block.gender || "unknown";
        const confidence = block.confidence || 0;
        const segCount = block.segment_count || 1;

        let icon = "🤷";
        let label = "未知";
        let blockLabel = "";
        if (gender === "male") {
            icon = "👨";
            label = "男";
            blockLabel = "男声";
        } else if (gender === "female") {
            icon = "👩";
            label = "女";
            blockLabel = "女声";
        }

        const item = document.createElement("div");
        item.className = `speaker-segment ${gender}`;
        item.title = `点击定位到原文`;
        item.innerHTML = `
            <span class="gender-icon">${icon}</span>
            <span class="segment-time">${formatTime(block.start)} - ${formatTime(block.end)}</span>
            <span class="segment-text" title="${escapeHtml(block.text)}">${escapeHtml(block.text.substring(0, 60))}${block.text.length > 60 ? '...' : ''}</span>
            <span class="segment-confidence">${blockLabel} ${Math.round(confidence * 100)}% · ${block.duration}秒 · ${segCount}句</span>
        `;

        // 点击定位到原文
        item.addEventListener("click", () => {
            const fullText = sourceText.value;
            const idx = fullText.indexOf(block.text.substring(0, 20));
            if (idx !== -1) {
                sourceText.focus();
                sourceText.setSelectionRange(idx, idx + Math.min(block.text.length, fullText.length - idx));
                const textBefore = fullText.substring(0, idx);
                const lineHeight = parseFloat(getComputedStyle(sourceText).lineHeight) || 22;
                const paddingTop = parseFloat(getComputedStyle(sourceText).paddingTop) || 16;
                const lines = textBefore.split("\n").length;
                sourceText.scrollTop = Math.max(0, (lines - 1) * lineHeight + paddingTop - 60);
                sourceText.classList.remove("highlight-pulse");
                void sourceText.offsetWidth;
                sourceText.classList.add("highlight-pulse");
            }
        });

        speakerTimeline.appendChild(item);
    });

    // 更新标题显示统计
    const header = speakerSection.querySelector(".section-header h3");
    if (header && stats) {
        let statsText = "🎤 说话人标注";
        if (stats.male_blocks > 0) statsText += ` · 👨${stats.male_blocks}段男声 (${stats.male_duration}秒)`;
        if (stats.female_blocks > 0) statsText += ` · 👩${stats.female_blocks}段女声 (${stats.female_duration}秒)`;
        header.textContent = statsText;
    }

    speakerSection.classList.remove("hidden");
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

function formatTime(seconds) {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
}

dismissSpeakerBtn.addEventListener("click", () => {
    speakerSection.classList.add("hidden");
});

// ========== 文本编辑区 ==========
sourceText.addEventListener("input", () => {
    updateWordCount();
    translateBtn.disabled = !sourceText.value.trim();
    proofreadBtn.disabled = !sourceText.value.trim();
});

copySourceBtn.addEventListener("click", () => {
    if (!sourceText.value.trim()) {
        showToast("没有可复制的内容");
        return;
    }
    navigator.clipboard.writeText(sourceText.value).then(() => {
        showToast("已复制到剪贴板");
    }).catch(() => {
        sourceText.select();
        showToast("请手动复制 (Ctrl+C)");
    });
});

clearSourceBtn.addEventListener("click", () => {
    if (sourceText.value && confirm("确定清空识别文本吗？")) {
        sourceText.value = "";
        updateWordCount();
        translateBtn.disabled = true;
    }
});

function updateWordCount() {
    const text = sourceText.value.trim();
    const count = text.length;
    wordCount.textContent = `${count} 字`;
}

// ========== 翻译 ==========
translateBtn.addEventListener("click", performTranslation);

// 当源文本有内容时，也可以直接按 Ctrl+Enter 翻译
sourceText.addEventListener("keydown", (e) => {
    if (e.ctrlKey && e.key === "Enter") {
        e.preventDefault();
        performTranslation();
    }
});

async function performTranslation() {
    const text = sourceText.value.trim();
    if (!text) {
        showToast("请输入或上传需要翻译的文本");
        return;
    }

    // 更新 UI
    translateBtn.disabled = true;
    translateProgress.classList.remove("hidden");
    resultPlaceholder.classList.add("hidden");
    resultContent.classList.add("hidden");

    try {
        const response = await fetch("/api/translate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                text: text,
                source: sourceLang.value,
                target: targetLang.value,
            }),
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "翻译失败");
        }

        translatedText = data.translated_text;
        resultContent.textContent = translatedText;
        resultContent.classList.remove("hidden");
        resultPlaceholder.classList.add("hidden");

        const targetName = targetLang.options[targetLang.selectedIndex].text;
        showToast(`翻译完成 → ${targetName}`);

    } catch (error) {
        resultPlaceholder.textContent = `翻译失败: ${error.message}`;
        resultPlaceholder.classList.remove("hidden");
        resultContent.classList.add("hidden");
        showToast(`翻译失败: ${error.message}`);
        console.error("Translation error:", error);
    } finally {
        translateBtn.disabled = false;
        translateProgress.classList.add("hidden");
    }
}

// ========== 交换语言 ==========
swapLangBtn.addEventListener("click", () => {
    if (sourceLang.value === "auto") {
        showToast("自动检测模式下无法交换语言");
        return;
    }

    const temp = sourceLang.value;
    sourceLang.value = targetLang.value;
    targetLang.value = temp;

    // 如果有翻译结果，交换文本
    if (translatedText) {
        sourceText.value = translatedText;
        updateWordCount();
        translatedText = "";
        clearResult();
        showToast("已交换语言和文本");
    }
});

// ========== 翻译结果操作 ==========
copyResultBtn.addEventListener("click", () => {
    if (!translatedText) {
        showToast("没有可复制的翻译结果");
        return;
    }
    navigator.clipboard.writeText(translatedText).then(() => {
        showToast("翻译结果已复制到剪贴板");
    }).catch(() => {
        showToast("复制失败，请手动选择复制");
    });
});

clearResultBtn.addEventListener("click", () => {
    clearResult();
});

function clearResult() {
    translatedText = "";
    resultContent.textContent = "";
    resultContent.classList.add("hidden");
    resultPlaceholder.textContent = "翻译结果将显示在这里";
    resultPlaceholder.classList.remove("hidden");
}

// ========== 目标语言变更时自动翻译 ==========
let autoTranslateTimeout;
targetLang.addEventListener("change", () => {
    if (sourceText.value.trim()) {
        clearTimeout(autoTranslateTimeout);
        autoTranslateTimeout = setTimeout(performTranslation, 500);
    }
});
