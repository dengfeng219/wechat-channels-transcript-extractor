# -*- coding: utf-8 -*-
"""
语音识别引擎封装。

支持三种引擎（全部本地推理，音频不出本机）：
  paraformer  —— 阿里 FunASR 中文模型，带标点与句级时间戳（默认，中文口播首选）
  sensevoice  —— FunASR SenseVoiceSmall，速度最快
  whisper     —— faster-whisper，多语种/中英混说更强

模型默认从 ModelScope 下载（国内可达），缓存到项目 models 目录。
"""
import os
import re
import sys
import time

__all__ = ["ASREngine", "ENGINES", "check_env"]

ENGINES = ("paraformer", "sensevoice", "whisper")

# SenseVoice 输出中的富文本标签，如 <|zh|><|NEUTRAL|><|Speech|>
_RICH_TAG = re.compile(r"<\|[^|]*\|>")


def _project_models_dir():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    legacy = os.path.join(here, "models")

    # 模型必须放在纯英文路径。原因：
    #   sentencepiece（SenseVoice 的分词器）和 whisper 的分词器在 Windows 上
    #   用窄字符路径打开文件，路径里有中文就打不开。这类失败只在「识别」时出现
    #   （那时才碰分词器），加载阶段一切正常，所以很难查。
    #   （试过用目录联接绕开：库内部会解析回真实路径，没用。）
    # 项目目录名是中文时，就把缓存放到 %LOCALAPPDATA%\WxTranscriptModels。
    if here.isascii():
        d = legacy
    else:
        base = (os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
                or os.path.expanduser("~"))
        d = os.path.join(base, "WxTranscriptModels")
    os.makedirs(d, exist_ok=True)
    return d


def _setup_cache_env():
    """把模型缓存固定在项目目录内（必要时经英文联接路径），避免散落到用户主目录。"""
    md = _project_models_dir()
    os.environ.setdefault("MODELSCOPE_CACHE", os.path.join(md, "modelscope"))
    os.environ.setdefault("HF_HOME", os.path.join(md, "huggingface"))
    # HuggingFace 在本网络环境不可达时走镜像
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


def _pick_device(prefer=None):
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda:0"
    except Exception:
        pass
    return "cpu"


def check_env():
    """检查各引擎可用性，供界面展示。"""
    _setup_cache_env()
    out = {"torch": None, "cuda": False, "gpu": None, "funasr": None,
           "faster_whisper": None, "av": None}
    try:
        import torch
        out["torch"] = torch.__version__
        out["cuda"] = bool(torch.cuda.is_available())
        if out["cuda"]:
            out["gpu"] = torch.cuda.get_device_name(0)
    except Exception as e:
        out["torch"] = "未安装 (%s)" % e
    try:
        import funasr
        out["funasr"] = getattr(funasr, "__version__", "已安装")
    except Exception as e:
        out["funasr"] = "未安装"
    try:
        import faster_whisper
        out["faster_whisper"] = getattr(faster_whisper, "__version__", "已安装")
    except Exception:
        out["faster_whisper"] = "未安装"
    try:
        import av
        out["av"] = av.__version__
    except Exception:
        out["av"] = "未安装"
    return out


class ASREngine(object):
    """懒加载的 ASR 引擎；同一个实例可重复转写多个文件。"""

    def __init__(self, engine="paraformer", device=None, verbose=True,
                 model_dir=None, whisper_model="large-v3"):
        if engine not in ENGINES:
            raise ValueError("未知引擎: %s" % engine)
        self.engine = engine
        self.verbose = verbose
        self._model = None
        self._device = device or _pick_device()
        self._model_dir = model_dir
        self.whisper_model = whisper_model

    # ---------- 内部 ----------
    def _log(self, msg):
        if self.verbose:
            print(msg, flush=True)

    def _load(self):
        if self._model is not None:
            return self._model
        _setup_cache_env()
        if self.engine in ("paraformer", "sensevoice"):
            self._model = self._load_funasr()
        else:
            self._model = self._load_whisper()
        return self._model

    def _load_funasr(self):
        from funasr import AutoModel
        common = dict(device=self._device, hub="ms", disable_update=True, disable_pbar=True)
        if self._model_dir:
            common["cache_dir"] = self._model_dir

        if self.engine == "sensevoice":
            self._log("[ASR] 加载 SenseVoiceSmall（设备 %s）..." % self._device)
            return AutoModel(
                model="iic/SenseVoiceSmall",
                vad_model="fsmn-vad",
                vad_kwargs={"max_single_segment_time": 30000},
                **common)
        self._log("[ASR] 加载 Paraformer-zh + 标点 + VAD（设备 %s）..." % self._device)
        return AutoModel(
            model="paraformer-zh",
            vad_model="fsmn-vad",
            punc_model="ct-punc",
            **common)

    def _load_whisper(self):
        from faster_whisper import WhisperModel
        device = "cuda" if self._device.startswith("cuda") else "cpu"
        compute = "float16" if device == "cuda" else "int8"
        self._log("[ASR] 加载 faster-whisper %s（%s/%s）..." % (self.whisper_model, device, compute))
        return WhisperModel(self.whisper_model, device=device, compute_type=compute,
                            download_root=os.path.join(_project_models_dir(), "whisper"))

    # ---------- 对外 ----------
    def transcribe(self, wav_path, language="zh", progress=None):
        """
        转写单个 16kHz 单声道 WAV。

        返回 dict: {text, segments:[{start,end,text}], engine, language, elapsed}
        """
        t0 = time.time()
        self._load()
        if self.engine == "sensevoice":
            r = self._run_sensevoice(wav_path, language)
        elif self.engine == "paraformer":
            r = self._run_paraformer(wav_path)
        else:
            r = self._run_whisper(wav_path, language)
        r["engine"] = self.engine
        r["language"] = language
        r["elapsed"] = time.time() - t0
        self._log("[ASR] 完成，用时 %.1f 秒，%d 字" % (r["elapsed"], len(r["text"])))
        return r

    def _run_paraformer(self, wav_path):
        res = self._model.generate(input=wav_path, batch_size_s=300,
                                   sentence_timestamp=True)
        if not res:
            raise RuntimeError("Paraformer 未返回结果")
        item = res[0]
        text = (item.get("text") or "").strip()
        segments = []
        for s in (item.get("sentence_info") or []):
            seg_text = (s.get("text") or "").strip()
            if not seg_text:
                continue
            segments.append({
                "start": float(s.get("start", 0)) / 1000.0,
                "end": float(s.get("end", 0)) / 1000.0,
                "text": seg_text,
            })
        if not segments and text:
            segments = [{"start": 0.0, "end": 0.0, "text": text}]
        return {"text": text, "segments": segments}

    def _run_sensevoice(self, wav_path, language):
        lang = "auto" if language in ("auto", None, "") else language
        res = self._model.generate(
            input=wav_path, cache={}, language=lang, use_itn=True,
            batch_size_s=60, merge_vad=True, merge_length_s=15)
        if not res:
            raise RuntimeError("SenseVoice 未返回结果")
        raw = res[0].get("text") or ""
        try:
            from funasr.utils.postprocess_utils import rich_transcription_postprocess
            text = rich_transcription_postprocess(raw)
        except Exception:
            text = _RICH_TAG.sub("", raw)
        text = text.strip()
        segments = [{"start": 0.0, "end": 0.0, "text": text}] if text else []
        return {"text": text, "segments": segments}

    def _run_whisper(self, wav_path, language):
        lang = None if language in ("auto", None, "") else language
        segs, info = self._model.transcribe(
            wav_path, language=lang, beam_size=5, vad_filter=True,
            initial_prompt="以下是普通话内容，请使用简体中文并加标点。")
        segments, parts = [], []
        for s in segs:
            t = (s.text or "").strip()
            if not t:
                continue
            segments.append({"start": float(s.start), "end": float(s.end), "text": t})
            parts.append(t)
        return {"text": "".join(parts), "segments": segments}
