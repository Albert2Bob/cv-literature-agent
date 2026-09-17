---
title: Transformer 与视觉 Transformer
domain: 计算机视觉
topic: 注意力机制 / ViT / Swin
---

# Transformer 与视觉 Transformer（ViT / Swin）

## 1. 自注意力机制（Self-Attention）

> 关键词：self-attention、QKV、缩放点积、多头注意力

自注意力把输入序列 $X \in \mathbb{R}^{N\times d}$ 通过三组线性变换投影为查询 $Q$、键 $K$、值 $V$：

$$\text{Attention}(Q,K,V) = \text{softmax}\!\left(\frac{QK^\top}{\sqrt{d_k}}\right)V$$

**为什么除以 $\sqrt{d_k}$**：当维度 $d_k$ 较大时，$QK^\top$ 的点积方差随维度线性增长，softmax 会进入饱和区，梯度极小。除以 $\sqrt{d_k}$ 把方差拉回 1 量级，保证训练稳定。

**多头注意力（MHA）**：把 $d$ 维拆成 $h$ 个头并行做注意力，每个头维度为 $d/h$，最后拼接再线性投影。不同头可以关注不同的关系（局部纹理、长程依赖、颜色通道等）。

**复杂度**：注意力矩阵是 $N\times N$，因此时间和显存复杂度都是 $O(N^2 d)$。这是 ViT 处理高分辨率图像的核心瓶颈。

## 2. 位置编码（Positional Encoding）

> 关键词：position embedding、正弦编码、可学习编码、RoPE

自注意力本身是置换不变的，必须显式注入位置信息：

- **正弦编码**（原始 Transformer）：固定公式生成，可外推到更长序列。
- **可学习位置编码**（ViT、BERT）：作为参数学习，简单但无法外推到训练时未见过的长度。
- **相对位置编码 / RoPE**：编码相对距离，外推能力更好，广泛用于大模型与部分视觉模型。

**ViT 的做法**：把图像切成 $16\times16$ 的 patch，展平后线性投影为 token，再叠加一个可学习的位置编码。位置编码的分辨率因此与输入分辨率强绑定——改变输入尺寸时需要插值位置编码，这正是 ViT 难以直接迁移到密集预测任务的原因之一。

## 3. ViT：把图像当序列

> 关键词：ViT、patch embedding、[CLS] token、归纳偏置

ViT（Vision Transformer）的结构与 BERT 几乎相同：

1. **Patch Embedding**：图像 $224\times224$ 切成 $14\times14=196$ 个 $16\times16$ patch，每个 patch 线性投影成 $D$ 维向量。
2. **位置编码**：叠加可学习位置编码。
3. **Transformer Encoder**：$L$ 层，每层是 MHA + MLP，前置 LayerNorm（pre-norm）。
4. **分类头**：使用额外的 `[CLS]` token 的输出，或对所有 token 做平均池化。

**关键结论（论文的核心发现）**：ViT 缺少 CNN 的归纳偏置（局部性、平移等变性、层次性），因此在中小数据集（如 ImageNet-1k）上不如同等规模的 CNN；只有在超大规模数据（JFT-300M，3 亿张图）上预训练后，ViT 才能超越 CNN。也就是说，**ViT 把"结构先验"换成了"数据量"**。

**DeiT** 通过强数据增强（RandAugment、Mixup、CutMix）、蒸馏 token 与正则化，证明只用 ImageNet-1k 也能训练出有竞争力的 ViT。

## 4. Swin Transformer：层次化 + 移动窗口

> 关键词：Swin、shifted window、窗口注意力、层次化特征

Swin 针对 ViT 的两个问题给出解法：

**问题一：复杂度是全局的 $O(N^2)$。**
解法：**窗口注意力（WSA）**——把特征图划分为不重叠的 $M\times M$ 窗口（默认 $M=7$），只在窗口内做自注意力，复杂度降为线性 $O(N)$。

**问题二：窗口之间没有信息交流。**
解法：**移动窗口（Shifted Window, SWSA）**——下一层的窗口整体平移 $\lfloor M/2 \rfloor$ 个像素，使原本被切开的位置落入同一窗口。相邻两层交替使用 WSA 与 SWSA，就实现了跨窗口的信息传递。

工程上，移动窗口会产生许多尺寸不一的碎片，实现时用 **masked attention**（给不同窗口来源的 token 打上不同的注意力掩码）来避免显式 padding 带来的额外开销。

**Swin 还引入了层次化结构**：通过 patch merging 逐步下采样（$4\times$、$8\times$、$16\times$、$32\times$ 四个 stage），输出多尺度特征图。这一点与 ResNet 一致，因此 Swin 可以直接替换检测与分割框架中的 CNN backbone（如 Swin + FPN 用于 Mask R-CNN）。

## 5. 常见视觉 Transformer 对比

> 关键词：ViT、DeiT、Swin、PVT、ConvNeXt

| 模型 | 注意力范围 | 是否层次化 | 适合的任务 | 备注 |
| :--- | :--- | :--- | :--- | :--- |
| ViT | 全局 | 否 | 图像分类 | 需大数据预训练 |
| DeiT | 全局 | 否 | 图像分类 | 蒸馏 + 强增强，单机可训 |
| Swin | 局部窗口 + 移动 | 是 | 分类 / 检测 / 分割 | 密集预测任务的主流选择 |
| PVT | 金字塔 + 稀疏注意力 | 是 | 检测 / 分割 | 引入空间缩减降低计算量 |
| ConvNeXt | 卷积 | 是 | 分类 / 检测 / 分割 | 用现代训练配方重设计 ResNet，证明卷积仍具竞争力 |

## 6. 实践建议

> 关键词：选型、预训练权重、显存

- **数据量少（< 10 万张）**：优先 CNN（ResNet / ConvNeXt）或 Swin-Tiny 并加载 ImageNet 预训练权重；直接训 ViT 容易欠拟合。
- **需要密集预测（检测/分割）**：优先 Swin / PVT / ConvNeXt 这类层次化 backbone，便于接 FPN。
- **显存受限**：全局注意力在 $1024\times1024$ 输入下注意力矩阵就是 $4096\times4096$，必选窗口/稀疏注意力，或改用卷积。
- **小目标密集场景**：窗口注意力会割裂小目标，需增大窗口或改用混合结构（如 CvT、Conformer）。
- **注意位置编码插值**：更换输入分辨率时，ViT 的位置编码必须插值，否则性能大幅下降。
