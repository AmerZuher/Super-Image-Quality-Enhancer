"""The built-in model catalog.

Weights are never stored in git. Each model lists where to download its files, their exact
size and SHA-256, and its license. Only licenses that allow commercial use are accepted
(``COMMERCIAL_SAFE``); a unit test enforces it. Sources are GitHub release assets, GitHub LFS
files pinned to a commit, or the authors' own buckets, all reachable where Hugging Face is blocked.
"""

from dataclasses import dataclass, field
from typing import Literal

Task = Literal["upscale", "denoise", "deblur", "colorize", "erase", "background", "face", "embed"]
Arch = Literal[
    "spandrel", "siqe_classic", "isnet_onnx", "gfpgan", "clip", "forge", "onnx", "lama_onnx", "siggraph_color"
]
Speed = Literal["fast", "balanced", "slow"]

COMMERCIAL_SAFE = frozenset({"MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0"})

_SIQE_REPO = "https://github.com/AmerZuher/Super-Image-Quality-Enhancer"
# The original Keras weights, kept in this repository's history before the rebuild.
_SIQE_V10 = (
    "https://raw.githubusercontent.com/AmerZuher/Super-Image-Quality-Enhancer/"
    "588eb1019e5f49e6e6964b9f8b99c21a03c24eb3/backend/app/utils/models/v10.h5"
)
_ESRGAN = "https://github.com/xinntao/Real-ESRGAN"


@dataclass(frozen=True)
class ModelFile:
    name: str
    url: str
    sha256: str
    size: int
    # Converted after download into this file name (see siqe.ai.convert).
    convert_to: str | None = None

    @property
    def stored_name(self) -> str:
        return self.convert_to or self.name


@dataclass(frozen=True)
class ModelSpec:
    id: str
    name: str
    task: Task
    arch: Arch
    scale: int
    summary: str
    license: str
    license_url: str
    homepage: str
    files: tuple[ModelFile, ...]
    # Pixels of surrounding image each tile needs, so the model's view never reaches a seam.
    context: int = 24
    channels: Literal["rgb", "y"] = "rgb"
    # Input sides must be a multiple of this, and tiles at least this big (with context), for
    # models that can't say so themselves (ONNX exports).
    multiple: int = 1
    min_input: int = 0
    # ONNX outputs in 0..255 instead of 0..1 (found when you add your own model).
    output_range: int = 1
    # Measured on this machine's CPU, for models you add yourself; used to warn about long runs.
    seconds_per_mp: float | None = None
    speed: Speed = "balanced"
    recommended: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def size_bytes(self) -> int:
        return sum(f.size for f in self.files)

    @property
    def weights(self) -> ModelFile:
        return self.files[0]


MODELS: tuple[ModelSpec, ...] = (
    ModelSpec(
        id="realesrgan-x4plus",
        name="Real-ESRGAN x4plus",
        task="upscale",
        arch="spandrel",
        scale=4,
        summary="The all-round choice for photos: sharpens detail and cleans up noise and JPEG blocks.",
        license="BSD-3-Clause",
        license_url=f"{_ESRGAN}/blob/master/LICENSE",
        homepage=_ESRGAN,
        files=(
            ModelFile(
                "RealESRGAN_x4plus.pth",
                f"{_ESRGAN}/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
                "4fa0d38905f75ac06eb49a7951b426670021be3018265fd191d2125df9d682f1",
                67040989,
            ),
        ),
        recommended=True,
        tags=("photos", "denoise", "jpeg"),
    ),
    ModelSpec(
        id="realesrgan-x2plus",
        name="Real-ESRGAN x2plus",
        task="upscale",
        arch="spandrel",
        scale=2,
        summary="Doubles the size with the same clean-up as x4plus; a gentler result for good sources.",
        license="BSD-3-Clause",
        license_url=f"{_ESRGAN}/blob/master/LICENSE",
        homepage=_ESRGAN,
        files=(
            ModelFile(
                "RealESRGAN_x2plus.pth",
                f"{_ESRGAN}/releases/download/v0.2.1/RealESRGAN_x2plus.pth",
                "49fafd45f8fd7aa8d31ab2a22d14d91b536c34494a5cfe31eb5d89c2fa266abb",
                67061725,
            ),
        ),
        tags=("photos",),
    ),
    ModelSpec(
        id="realesr-general-x4v3",
        name="Real-ESRGAN General v3",
        task="upscale",
        arch="spandrel",
        scale=4,
        summary="A small, fast ×4 model (5 MB). Good on the CPU and for previews.",
        license="BSD-3-Clause",
        license_url=f"{_ESRGAN}/blob/master/LICENSE",
        homepage=_ESRGAN,
        files=(
            ModelFile(
                "realesr-general-x4v3.pth",
                f"{_ESRGAN}/releases/download/v0.2.5.0/realesr-general-x4v3.pth",
                "8dc7edb9ac80ccdc30c3a5dca6616509367f05fbc184ad95b731f05bece96292",
                4885111,
            ),
        ),
        context=32,
        speed="fast",
        tags=("photos", "cpu"),
    ),
    ModelSpec(
        id="swinir-m-x4-realsr",
        name="SwinIR-M ×4 (real-world)",
        task="upscale",
        arch="spandrel",
        scale=4,
        summary="A transformer that keeps fine texture such as foliage and fabric. Slower.",
        license="Apache-2.0",
        license_url="https://github.com/JingyunLiang/SwinIR/blob/main/LICENSE",
        homepage="https://github.com/JingyunLiang/SwinIR",
        files=(
            ModelFile(
                "003_realSR_BSRGAN_DFO_s64w8_SwinIR-M_x4_GAN.pth",
                "https://github.com/JingyunLiang/SwinIR/releases/download/v0.0/"
                "003_realSR_BSRGAN_DFO_s64w8_SwinIR-M_x4_GAN.pth",
                "b9afb61e65e04eb7f8aba5095d070bbe9af28df76acd0c9405aeb33b814bcfc6",
                67129861,
            ),
        ),
        context=32,
        speed="slow",
        tags=("texture",),
    ),
    ModelSpec(
        id="siqe-classic",
        name="SIQE Classic ×3",
        task="upscale",
        arch="siqe_classic",
        scale=3,
        summary="The original Super Image Quality Enhancer: a residual dense network on brightness detail.",
        license="MIT",
        license_url=f"{_SIQE_REPO}/blob/main/LICENSE",
        homepage=f"{_SIQE_REPO}/tree/main/docs/research",
        files=(
            ModelFile(
                "v10.h5",
                _SIQE_V10,
                "9bf7aea18097cac83be849ba6fcb27631f3ab3e7917c5d94d93c142262699343",
                4410448,
                convert_to="siqe-classic-v10.safetensors",
            ),
        ),
        context=16,
        channels="y",
        speed="fast",
        tags=("yours",),
    ),
    ModelSpec(
        id="scunet-real-psnr",
        name="SCUNet denoise",
        task="denoise",
        arch="spandrel",
        scale=1,
        summary="Removes real camera noise while keeping detail; same size out.",
        license="Apache-2.0",
        license_url="https://github.com/cszn/SCUNet/blob/main/LICENSE",
        homepage="https://github.com/cszn/SCUNet",
        files=(
            ModelFile(
                "scunet_color_real_psnr.pth",
                "https://github.com/cszn/KAIR/releases/download/v1.0/scunet_color_real_psnr.pth",
                "fa78899ba2caec9d235a900e91d96c689da71c42029230c2028b00f09f809c2e",
                71982841,
            ),
        ),
        context=32,
        recommended=True,
        tags=("noise",),
    ),
    ModelSpec(
        id="isnet-general",
        name="ISNet background removal",
        task="background",
        arch="isnet_onnx",
        scale=1,
        summary="Separates the subject from the background and saves a PNG with transparency.",
        license="Apache-2.0",
        license_url="https://github.com/xuebinqin/DIS/blob/main/LICENSE.md",
        homepage="https://github.com/xuebinqin/DIS",
        files=(
            ModelFile(
                "isnet-general-use.onnx",
                "https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx",
                "60920e99c45464f2ba57bee2ad08c919a52bbf852739e96947fbb4358c0d964a",
                178648008,
            ),
        ),
        context=0,
        recommended=True,
        tags=("cutout",),
    ),
)

MODELS = (
    *MODELS,
    ModelSpec(
        id="gfpgan-v1.4",
        name="GFPGAN v1.4 faces",
        task="face",
        arch="gfpgan",
        scale=1,
        summary=(
            "Finds faces with RetinaFace (MIT) and restores blurry or damaged ones; also an upscale option."
        ),
        license="Apache-2.0",
        license_url="https://github.com/TencentARC/GFPGAN/blob/master/LICENSE",
        homepage="https://github.com/TencentARC/GFPGAN",
        files=(
            ModelFile(
                "GFPGANv1.4.pth",
                "https://github.com/TencentARC/GFPGAN/releases/download/v1.3.4/GFPGANv1.4.pth",
                "e2cd4703ab14f4d01fd1383a8a8b266f9a5833dacee8e6a79d3bf21a1b6be5ad",
                348632874,
            ),
            ModelFile(
                "detection_Resnet50_Final.pth",
                "https://github.com/xinntao/facexlib/releases/download/v0.1.0/detection_Resnet50_Final.pth",
                "6d1de9c2944f2ccddca5f5e010ea5ae64a39845a86311af6fdf30841b0a5a16d",
                109497761,
            ),
        ),
        context=0,
        recommended=True,
        tags=("faces", "portraits"),
    ),
)

_OPEN_CLIP = "https://github.com/mlfoundations/open_clip"

MODELS = (
    *MODELS,
    ModelSpec(
        id="clip-vit-b32",
        name="CLIP ViT-B/32 search",
        task="embed",
        arch="clip",
        scale=1,
        summary=(
            "Understands what a photo shows: powers Library search by description, similar images "
            "and automatic tags. Runs on the CPU."
        ),
        license="MIT",
        license_url=f"{_OPEN_CLIP}/blob/main/LICENSE",
        homepage=_OPEN_CLIP,
        files=(
            ModelFile(
                "vit_b_32-quickgelu-laion400m_e32-46683a32.pt",
                f"{_OPEN_CLIP}/releases/download/v0.2-weights/vit_b_32-quickgelu-laion400m_e32-46683a32.pt",
                "46683a32721d5c68911153698992361285d20ca690bb4f317c11e45c03d798fa",
                605159845,
                convert_to="clip-vit-b32.safetensors",
            ),
            ModelFile(
                "bpe_simple_vocab_16e6.txt.gz",
                "https://raw.githubusercontent.com/mlfoundations/open_clip/v2.24.0/"
                "src/open_clip/bpe_simple_vocab_16e6.txt.gz",
                "924691ac288e54409236115652ad4aa250f48203de50a9e4722a6ecd48d6804a",
                1356917,
            ),
        ),
        context=0,
        speed="fast",
        recommended=True,
        tags=("library", "search"),
    ),
)

# OpenCV Zoo keeps ONNX exports in Git LFS; pinned to a commit so the files can't change under us.
_OPENCV_ZOO = (
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/47534e27c9851bb1128ccc0102f1145e27f23f98"
)
_COLORIZATION = "https://github.com/richzhang/colorization"

MODELS = (
    *MODELS,
    ModelSpec(
        id="nafnet-deblur",
        name="NAFNet deblur",
        task="deblur",
        arch="onnx",
        scale=1,
        summary=(
            "Removes motion blur and camera shake (trained on GoPro footage). Runs on the CPU, tile by tile."
        ),
        license="MIT",
        license_url="https://github.com/megvii-research/NAFNet/blob/main/LICENSE",
        homepage="https://github.com/megvii-research/NAFNet",
        files=(
            ModelFile(
                "deblurring_nafnet_2025may.onnx",
                f"{_OPENCV_ZOO}/models/deblurring_nafnet/deblurring_nafnet_2025may.onnx",
                "07263f416febecce10193dd648e950b22e397cf521eedab1a114ef77b2bc9587",
                91736251,
            ),
        ),
        context=32,
        multiple=16,
        min_input=384,
        speed="slow",
        tags=("blur",),
    ),
    ModelSpec(
        id="lama-erase",
        name="LaMa object eraser",
        task="erase",
        arch="lama_onnx",
        scale=1,
        summary="Paint over something and it's removed, with the background filled in. Best for small to "
        "medium objects. Runs on the CPU.",
        license="Apache-2.0",
        license_url="https://github.com/advimman/lama/blob/main/LICENSE",
        homepage="https://github.com/advimman/lama",
        files=(
            ModelFile(
                "inpainting_lama_2025jan.onnx",
                f"{_OPENCV_ZOO}/models/inpainting_lama/inpainting_lama_2025jan.onnx",
                "7df918ac3921d3daf0aae1d219776cf0dc4e4935f035af81841b40adcf74fdf2",
                92591623,
            ),
        ),
        context=0,
        recommended=True,
        tags=("erase", "retouch"),
    ),
    ModelSpec(
        id="siggraph17-colorize",
        name="Colorize (SIGGRAPH 2017)",
        task="colorize",
        arch="siggraph_color",
        scale=1,
        summary="Adds plausible colour to black and white photos, keeping every detail of the original.",
        license="BSD-2-Clause",
        license_url=f"{_COLORIZATION}/blob/master/LICENSE",
        homepage=_COLORIZATION,
        files=(
            ModelFile(
                "siggraph17-df00044c.pth",
                "https://colorizers.s3.us-east-2.amazonaws.com/siggraph17-df00044c.pth",
                "df00044c0a4d7c3edcecf6f75437ce346a66e7a42612d9b968e1a7e17dbc6f66",
                136787426,
            ),
        ),
        context=0,
        speed="fast",
        recommended=True,
        tags=("old photos",),
    ),
)

# Models that run on the CPU worker with ONNX Runtime; the rest need the GPU worker's PyTorch.
CPU_ARCHS = frozenset({"isnet_onnx", "onnx", "lama_onnx"})
# Models whose output is computed tile by tile (the rest see the whole image at once).
TILED_ARCHS = frozenset({"spandrel", "siqe_classic", "forge", "onnx"})

FACE_MODEL_ID = "gfpgan-v1.4"
CLIP_MODEL_ID = "clip-vit-b32"
MODELS_BY_ID = {m.id: m for m in MODELS}
TASK_LABELS: dict[Task, str] = {
    "upscale": "Upscale",
    "denoise": "Denoise",
    "deblur": "Deblur",
    "colorize": "Colorize",
    "erase": "Erase objects",
    "background": "Remove background",
    "face": "Restore faces",
    "embed": "Search and tags",
}
