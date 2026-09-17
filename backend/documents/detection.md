---
title: 目标检测方法与评价指标
domain: 计算机视觉
topic: 目标检测 / 检测头 / NMS / mAP
---

# 目标检测：方法体系与评价指标

## 1. 检测范式分类

> 关键词：two-stage、one-stage、anchor-based、anchor-free、set prediction

| 范式 | 代表方法 | 核心流程 | 优点 | 缺点 |
| :--- | :--- | :--- | :--- | :--- |
| 两阶段 | Faster R-CNN、Cascade R-CNN | RPN 生成候选框 → RoI 对齐 → 分类 + 回归 | 精度高，尤其小目标 | 速度慢，流程复杂 |
| 单阶段 Anchor-based | SSD、RetinaNet、YOLOv3/v5 | 在密集先验框上直接分类回归 | 速度快，易部署 | 正负样本极不平衡 |
| 单阶段 Anchor-free | FCOS、CenterNet、YOLOv8/v11 | 预测中心点/关键点到边界的距离 | 无需设计 anchor，超参少 | 密集重叠目标易漏检 |
| 集合预测 | DETR、Deformable DETR | Transformer 解码 + 匈牙利匹配 | 无需 NMS，端到端 | 收敛慢，小目标弱 |

## 2. 两阶段检测

> 关键词：RPN、RoI Pooling、RoI Align、FPN

**RPN（Region Proposal Network）** 在特征图上每个位置铺设 $k$ 个 anchor，输出 2 分类（前景/背景）与 4 个回归偏移量。

**RoI Pooling 的量化误差**：把浮点候选框坐标取整再分桶池化，会引入像素级错位，对小目标尤其致命。**RoI Align** 改用双线性插值，取消量化，是 Mask R-CNN 的关键改进之一。

**FPN（Feature Pyramid Network）**：自顶向下路径 + 横向连接，把深层语义与浅层细节融合：
$$P_l = \text{Conv}\big(C_l + \text{Upsample}(P_{l+1})\big)$$
在小目标检测上，FPN 带来的提升往往比换 backbone 更大。

## 3. 单阶段检测与正负样本

> 关键词：Focal Loss、label assignment、ATSS、SimOTA

**Focal Loss** 解决前景/背景极端不平衡（一张图中负样本可达数万个）：

$$FL(p_t) = -\alpha_t (1-p_t)^{\gamma}\log(p_t)$$

$\gamma$ 通常取 2，作用是降低易分样本的权重，让训练聚焦在难例上。

**标签分配（label assignment）是单阶段检测的核心技巧**：

- 早期方法用 IoU 阈值硬分配，超参敏感。
- **ATSS**：对每个 GT 按候选框中心距离选取 top-k anchor，自适应计算 IoU 阈值，去掉人工阈值。
- **SimOTA / TAL**（YOLOX、YOLOv8）：把分配建模为最优传输问题，同时考虑分类与回归代价。
- 分配策略的差异，往往比网络结构改动带来更大的精度提升。

## 4. 检测头与损失

> 关键词：decoupled head、regression loss、IoU loss、CIoU、DFL

- **耦合头 vs 解耦头**：分类与回归对特征的需求不同，YOLOX 证明解耦头（各自独立分支）能显著提升精度。
- **边界框回归损失演进**：Smooth L1 → IoU → GIoU → DIoU → CIoU。CIoU 同时考虑重叠面积、中心距离与长宽比：

$$L_{CIoU} = 1 - IoU + \frac{\rho^2(b, b^{gt})}{c^2} + \alpha v$$

- **DFL（Distribution Focal Loss）**：YOLOv8 用离散分布建模边界距离，而非直接回归单值，提升定位精度。
- **YOLOv8 的损失组成**：分类损失（BCE）+ 回归损失（CIoU）+ DFL，按权重加权求和。

## 5. 后处理

> 关键词：NMS、Soft-NMS、class-agnostic NMS

**NMS（非极大值抑制）**：按置信度排序，逐个保留并抑制与其 IoU 超过阈值的框。IoU 阈值通常设 0.5~0.7。

**已知问题**：密集场景下相邻真实目标会被误抑制。改进方案：

- **Soft-NMS**：不直接删除，而是按 IoU 衰减其置信度，对密集人群检测更友好。
- **class-agnostic NMS**：跨类别一起抑制，减少类间重复框；配合类别置信度乘积使用。
- **DETR 类方法无需 NMS**，因为匈牙利匹配强制一对一分配。

## 6. 评价指标

> 关键词：IoU、Precision、Recall、AP、mAP、mAP50、mAP50-95、FPS

**IoU（交并比）**：
$$IoU = \frac{|A\cap B|}{|A\cup B|}$$

**Precision / Recall**：$P = \frac{TP}{TP+FP}$，$R = \frac{TP}{TP+FN}$。

**AP（Average Precision）**：对某一类别，将预测按置信度排序，画出 P-R 曲线，曲线下面积即 AP。实践中用 101 点插值：
$$AP = \frac{1}{101}\sum_{r\in\{0,0.01,\dots,1\}} P_{interp}(r)$$

**mAP**：所有类别 AP 的平均值。

- **mAP@0.5（mAP50）**：IoU 阈值为 0.5 时的 mAP。
- **mAP@0.5:0.95（mAP50-95）**：IoU 阈值从 0.5 到 0.95 每隔 0.05 取一次求平均，是 COCO 的主指标，对定位精度要求更严格。

**为什么 mAP50 高但 mAP50-95 低**：说明模型能框到目标但边界不够精确，通常是回归分支或特征分辨率不足。

**FPS / 参数量 / FLOPs**：部署侧关注指标。FPS 与硬件强相关，跨论文对比 FPS 意义有限，应看 FLOPs 与实测延迟。

## 7. 方法选型建议

> 关键词：选型、速度精度权衡、小目标

- **追求精度、离线场景**：Cascade R-CNN / DINO / Co-DETR + Swin backbone。
- **实时部署（边缘设备）**：YOLOv8n/s、PP-YOLOE、NanoDet。
- **端到端、不想调 NMS**：DETR 系（优先 Deformable DETR 或 DINO，收敛快很多）。
- **小目标多**：提高输入分辨率 + FPN/BiFPN + 增大 P2 层输出；避免过大的下采样倍数。
- **类别极不平衡**：Focal Loss 或类别重采样，关注长尾类别的 per-class AP 而不是只看 mAP。

## 8. 论文中对比实验的常见争议点

> 关键词：审稿、公平对比、消融

- **训练轮数不一致**：单阶段方法通常需要更长训练（300~500 epoch），若论文用短训练做对比，结论不成立。
- **是否使用预训练**：backbone 是否加载 ImageNet 权重，直接决定小数据集上的排名。
- **测试分辨率与增强**：test-time augmentation、多尺度测试会显著抬指标，必须对齐。
- **FPS 的测量硬件未说明**：不同 GPU、batch size、是否半精度都影响巨大。
- **只报 mAP50**：掩盖定位精度问题，COCO 数据集应报 mAP50-95。
