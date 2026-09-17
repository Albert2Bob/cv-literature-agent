---
title: 图像分割方法体系
domain: 计算机视觉
topic: 语义分割 / 实例分割 / 全景分割 / SAM
---

# 图像分割：语义、实例、全景与基础模型

## 1. 三类分割任务的区别

> 关键词：semantic segmentation、instance segmentation、panoptic segmentation

| 任务 | 输出 | 是否区分同类个体 | 典型数据集 | 典型指标 |
| :--- | :--- | :--- | :--- | :--- |
| 语义分割 | 每像素类别标签 | 否（同类连通） | Cityscapes、ADE20K、Pascal VOC | mIoU、像素准确率 |
| 实例分割 | 每个实例的掩码 + 类别 | 是 | COCO | mask AP、box AP |
| 全景分割 | 统一"可数事物 + 不可数背景" | 是 | COCO Panoptic、Cityscapes | PQ（Panoptic Quality） |

**语义分割与实例分割的关系**：实例分割可以看作「检测 + 逐实例二值分割」。Mask R-CNN 正是在 Faster R-CNN 上并行加了一个 mask 分支。

## 2. 语义分割：编码器-解码器范式

> 关键词：U-Net、FCN、skip connection、空洞卷积、DeepLab、ASPP

**FCN** 首次把分类网络的全连接层换成卷积，实现端到端逐像素预测，但上采样过于粗糙。

**U-Net** 的结构是「收缩路径 + 扩张路径」：

- 收缩路径（encoder）：卷积 + 池化，逐步降低分辨率、提取语义。
- 扩张路径（decoder）：上采样 + 与 encoder 对应层的特征**拼接（skip connection）**。
- 关键点：skip connection 把高分辨率的浅层细节直接送到解码器，弥补上采样丢失的边界信息。这让 U-Net 在**小数据集**（如医学影像，几百张图）上也能训练出好结果。

**空洞卷积（Dilated / Atrous Convolution）**：在卷积核元素之间插入空洞，不增加参数就扩大感受野，避免池化带来的分辨率损失。DeepLab 系列的核心。

**ASPP（Atrous Spatial Pyramid Pooling）**：并行使用多个不同空洞率的卷积 + 全局池化，捕获多尺度上下文，最后拼接融合。适合目标尺度差异大的场景。

**DeepLabv3+** = 骨干网络 + ASPP + 轻量解码器，是语义分割的经典强基线。

**SegFormer**：用层次化 Transformer（MiT）做 encoder，解码器极简（MLP + 上采样），证明"强 encoder + 弱 decoder"也能达到 SOTA，且推理速度快。

**遥感建筑的实践提示**：二分类（建筑/背景）任务中，U-Net 配预训练 encoder 往往比直接上 Transformer 更稳、更好复现；Transformer 的 patch 化会削弱细长边界的分割质量，需要更高输入分辨率来补偿。

## 3. 实例分割

> 关键词：Mask R-CNN、RoI Align、mask branch、SOLO、YOLACT

**Mask R-CNN** 在 Faster R-CNN 的每个 RoI 上增加一个小的 FCN 分支，输出 $28\times28$ 的二值掩码：

- 掩码预测与类别预测**解耦**：每个类别各预测一个掩码，分类分支决定用哪一个，避免了类间竞争。
- 用 **RoI Align** 替代 RoI Pooling，消除量化误差。
- 损失 = 分类损失 + 框回归损失 + 掩码二值交叉熵。

**单阶段实例分割**：

- **YOLACT**：并行生成一组原型掩码 + 预测每个实例的掩码系数，线性组合得到实例掩码，实时性好。
- **SOLO / SOLOv2**：把实例分割转为「位置 + 尺寸」的密集预测，无需检测框，直接按位置分桶。

## 4. 全景分割

> 关键词：PQ、panoptic、things and stuff

全景分割统一处理：
- **Things**（可数实例）：人、车、动物。
- **Stuff**（不可数背景）：天空、道路、草地。

**PQ（Panoptic Quality）** 定义：

$$PQ = \underbrace{\frac{\sum_{(p,g)\in TP} IoU(p,g)}{|TP|}}_{SQ\ \text{识别质量}} \times \underbrace{\frac{|TP|}{|TP| + \frac{1}{2}|FP| + \frac{1}{2}|FN|}}_{RQ\ \text{识别率}}$$

PQ 同时惩罚分割不准（SQ 低）和漏检/误检（RQ 低），比 mIoU 更全面。

## 5. Segment Anything（SAM）与基础分割模型

> 关键词：SAM、promptable segmentation、zero-shot、SAM2

**SAM** 的核心设计：

1. **任务定义**：可提示分割（promptable segmentation）——给定点、框、掩码或文本提示，输出有效掩码。
2. **数据引擎**：模型辅助标注 + 人工修正 + 自动生成，最终产出 10 亿掩码的 SA-1B 数据集。
3. **模型结构**：图像编码器（ViT，只跑一次）+ 提示编码器 + 轻量掩码解码器。

**能力与局限**：SAM 的零样本泛化强，但**它只做分割，不给语义类别**。要做语义分割仍需外接分类器或与 CLIP 等模型结合。SAM2 进一步支持视频中的可提示分割与目标跟踪。

**工程用法**：把 SAM 当作「掩码生成器」，用检测框或点提示得到高质量掩码，再做后处理分类——这是弱监督/半自动标注的常见路线。

## 6. 分割损失函数

> 关键词：CrossEntropy、Dice、IoU loss、Focal、边界损失

| 损失 | 公式 | 适用场景 | 说明 |
| :--- | :--- | :--- | :--- |
| 交叉熵（CE） | $-\sum y\log p$ | 通用 | 类别极不平衡时被背景主导 |
| 加权 CE | 按类别频率加权 | 类别不平衡 | 需调权重 |
| Dice Loss | $1 - \frac{2|A\cap B|}{|A|+|B|}$ | 小目标、前景占比低 | 直接优化重叠度，与 IoU 相关 |
| IoU / Jaccard Loss | $1 - IoU$ | 评价指标直接对齐 | 训练早期梯度不稳定 |
| Focal Loss | 见检测文档 | 难例挖掘 | 抑制易分像素 |
| 边界损失（Boundary Loss） | 基于距离图 | 边界精度要求高 | 常与 Dice 组合使用 |

**常用组合**：$L = L_{CE} + L_{Dice}$，兼顾像素级监督与区域重叠度。遥感、医学等前景稀疏任务几乎都这么配。

## 7. 评价指标细节

> 关键词：mIoU、Dice、F1、像素准确率、边界 F1

**mIoU（平均交并比）**：
$$mIoU = \frac{1}{k}\sum_{i=1}^{k}\frac{TP_i}{TP_i + FP_i + FN_i}$$

**Dice 系数**：$Dice = \frac{2TP}{2TP+FP+FN}$。二分类下 Dice 与 IoU 单调等价：
$$F1 = Dice = \frac{2\,IoU}{1 + IoU}$$

**因此二分类任务的 IoU 与 F1 可以互相换算，同时报告两者没有额外信息量**；多分类下需按类别宏平均（macro）或按像素加权平均（micro），两者差异大时必须说明。

**像素准确率（PA）在类别不平衡时具有欺骗性**：若前景只占 5%，全预测背景就能拿到 95% 的 PA。此时必须报 mIoU 或 Dice。

**边界质量**：mIoU 对细长结构（道路、裂缝）不敏感，应额外报告 Boundary F1 或 HD95（医学常用）。

## 8. 分割任务常见踩坑

> 关键词：数据增强、类别不平衡、上采样、多尺度测试

- **标签错位**：增强时图像与掩码必须用同一随机参数（几何变换），否则边界处监督信号完全错误。
- **忽略标签（ignore index）**：数据集中「不确定/未标注」像素应设为 ignore，不计入损失与指标。
- **上采样方式**：双线性插值 + 卷积优于最近邻反卷积；转置卷积易产生棋盘伪影（checkerboard artifact）。
- **多尺度测试与滑动窗口**：高分辨率遥感/病理图像无法整图输入，需滑窗推理并做重叠区加权融合（overlap-tile）。
- **预训练编码器**：分割数据集普遍偏小，加载 ImageNet 预训练编码器通常比从头训练高 5~15 个点 mIoU。
