# LiquidGlassUI 设计规范

基于 Apple Liquid Glass 设计语言的 SwiftUI 组件库。版本 1.0。

---

## 1. 设计原则

| 原则 | 说明 |
|---|---|
| 内容为先 | 玻璃是「内容之上的材质层」，始终透出下层内容，不喧宾夺主 |
| 着色克制 | `tint` 仅表达语义倾向（不透明度 ≤ 0.35），不大面积实色覆盖 |
| 边缘发光 | 玻璃质感主要来自边缘高光与折射，而非中心填充 |
| 动效有质量 | 所有过渡使用带质量的弹性/平滑曲线，可感知但不拖沓（≤ 0.45s） |
| 单一主操作 | 每个视觉区域内 `prominent` 按钮不超过一个 |

## 2. 平台兼容矩阵

| 系统 | 渲染路径 | 说明 |
|---|---|---|
| macOS 26+ / iOS 26+ | 原生 `.glassEffect` / `Glass` | 完整液态玻璃：实时折射、interactive 提亮、玻璃间融合 |
| macOS 14–15 / iOS 17–18 | 降级材质模拟 | `ultraThinMaterial` + 顶部渐变高光 + 内描边 + 双层投影 |

降级逻辑封装在 `.lgGlass()` 修饰符内，调用方无需区分系统版本。

部署目标：macOS 14 / iOS 17。Swift 6.0+。

## 3. 设计令牌

### 3.1 间距（4pt 网格）

| 令牌 | 值 | 典型用途 |
|---|---|---|
| `LGSpacing.xxs` | 4 | 图标与文字间隙、Chip 内部 |
| `LGSpacing.xs` | 8 | 紧凑内边距、标签栏项 |
| `LGSpacing.sm` | 12 | 按钮垂直内边距 |
| `LGSpacing.md` | 16 | 卡片默认内边距、水平内边距 |
| `LGSpacing.lg` | 20 | 按钮水平内边距 |
| `LGSpacing.xl` | 24 | 区块间距 |
| `LGSpacing.xxl` | 32 | 大区块分隔 |

### 3.2 圆角（连续圆角 `.continuous`）

| 令牌 | 值 | 用途 |
|---|---|---|
| `LGRadius.small` | 10 | 缩略图、徽标 |
| `LGRadius.medium` | 16 | 输入框 |
| `LGRadius.large` | 22 | 卡片、导航栏 |
| `LGRadius.xlarge` | 28 | 大型容器、弹窗 |
| —（胶囊） | Capsule | 按钮、Chip、标签栏 |

### 3.3 动效

| 令牌 | 参数 | 用途 |
|---|---|---|
| `LGMotion.smooth` | `.smooth(duration: 0.35)` | 悬停、选中、展开过渡 |
| `LGMotion.press` | `.spring(response: 0.32, dampingFraction: 0.72)` | 按压回弹 |
| `LGMotion.morph` | `.smooth(duration: 0.45)` | 玻璃形态迁移（Tab 切换） |
| `LGMotion.pressScale` | 0.97 | 按压缩放比例 |

所有动效经 `LGMotion.adaptive(_:reduceMotion:)` 包裹：用户开启「减弱动态效果」时自动降级为 0.15s 淡入淡出。

### 3.4 颜色

不定义固定色板。语义色直接使用系统色（`.primary` / `.secondary` / `.accentColor`），深浅色模式自动适配。`tint` 参数仅用于倾向性着色。

## 4. 组件目录

### 4.1 玻璃修饰符 `.lgGlass()`（基础设施）

```swift
someView.lgGlass(_ variant: LGGlassVariant = .regular,
                 in shape: some Shape = Capsule(),
                 tint: Color? = nil,
                 interactive: Bool = false)
```

- `variant`：`.regular` 常规磨砂 / `.clear` 更通透
- `interactive`：按钮类开启，获得悬停/触摸提亮与弹性
- 任何视图均可获得玻璃表面，组件库全部组件基于此构建

### 4.2 按钮 `LGGlassButtonStyle`

```swift
Button("常规") {}.buttonStyle(.lgGlass)
Button("主操作") {}.buttonStyle(.lgGlassProminent(tint: .blue))
Button("文字") {}.buttonStyle(.lgPlain)
```

- standard：透明玻璃胶囊，次级操作
- prominent：tint 着色玻璃，白字，主操作（一屏一个）
- plain：无玻璃底纯文字，三级操作
- 按压：缩放 0.97 + 不透明度 0.88，弹性回弹；禁用态不透明度 0.45

### 4.3 卡片 `LGCard`

```swift
LGCard(padding: 16, radius: 22, tint: nil, hoverable: true) {
    // 内容
}
```

- 默认占满可用宽度，左对齐
- `hoverable`：macOS / iPad 指针悬停时放大 1.012 并提亮 3%
- `tint`：语义化着色（如设备卡片用 `.blue`）

### 4.4 输入框 `LGTextField`

```swift
LGTextField("搜索歌曲、歌手…", text: $query,
            systemImage: "magnifyingglass", submitLabel: .search) {
    // onSubmit
}
```

- 聚焦态：前置图标变为强调色 + `.bounce` 符号动效，外缘叠加 1.5pt 强调色描边
- 占位符、键盘提交类型可配

### 4.5 筛选标签 `LGChip`

```swift
LGChip("流行", isSelected: $selected, systemImage: "guitars", tint: .pink)
```

- 未选中：`.clear` 玻璃 + 次要色文字
- 选中：tint 着色玻璃 + 白字，切换带按压弹性

### 4.6 导航栏 `LGNavigationBar`

```swift
LGNavigationBar("音乐", subtitle: "资料库 · 8,432 首") {
    Button {} label: { Label("搜索", systemImage: "magnifyingglass") }
}
```

- 标题 + 可选副标题 + 尾部操作区（自动套用图标样式小玻璃按钮）
- 置于滚动内容之上时，下层内容滚动透出折射

### 4.7 标签栏 `LGTabBar`

```swift
LGTabBar(selection: $tab, items: [
    LGTabItem(id: "home", title: "首页", systemImage: "house"),
    LGTabItem(id: "browse", title: "浏览", systemImage: "square.grid.2x2"),
])
```

- 悬浮胶囊容器 + 选中项玻璃胶囊
- 新系统：`glassEffectID` 使选中玻璃在标签间流动迁移（morphing）
- 旧系统：`matchedGeometryEffect` 实现等价迁移
- 未选中项仅图标，选中项展开标题（`blurReplace` 过渡）
- 建议通过 `.safeAreaInset(edge: .bottom)` 挂载

### 4.8 氛围背景 `LGAmbientBackground`

```swift
ZStack {
    LGAmbientBackground(colors: [.blue, .purple, .pink])
    // 玻璃组件…
}
```

- 多层缓动径向渐变光斑，TimelineView 驱动缓慢漂移
- 玻璃表面必须有内容在背后才能体现折射——空背景上玻璃不可见
- 对辅助功能隐藏

## 5. 自适应规范

| 维度 | 策略 |
|---|---|
| 屏幕尺寸 | 组件不设固定宽高：`LGCard` 占满父宽；`LGTabBar` 由内容撑开；间距用令牌而非像素绝对值 |
| iPhone 紧凑宽度 | 使用 `ScrollView` + 垂直堆叠；Chips 区允许横向滚动或换行 |
| iPad / Mac 常规宽度 | 内容列建议 `frame(maxWidth: 720)` 居中；卡片可改为多列网格（`LazyVGrid` + `adaptive`） |
| 动态字体 | 全部文字使用语义字体（`.headline` / `.body` / `.caption`），随系统字号缩放；容器内边距足够容纳放大文本 |
| 深浅色模式 | 语义色自动适配；玻璃材质由系统按模式调整。两个模式都必须验证（玻璃在浅色下对比度更依赖边缘描边） |
| 减弱动态效果 | 所有动效经 `LGMotion.adaptive` 降级 |
| 指针设备（Mac/iPad） | `hoverable` 卡片与 interactive 玻璃提供悬停反馈；触控设备自动无效化 |
| 辅助功能 | Chip/Tab 带 `.isSelected` 特质；装饰性背景 `.accessibilityHidden`；标签栏容器命名 |

## 6. 接入指南

### 6.1 SwiftPM 依赖

```swift
// Package.swift
dependencies: [
    .package(path: "../LiquidGlassUI")
],
targets: [
    .target(name: "YourApp", dependencies: ["LiquidGlassUI"])
]
```

或在 Xcode 工程中：File → Add Package Dependencies → Add Local… 选择本目录。

### 6.2 运行演示

```swift
import SwiftUI
import LiquidGlassUI

@main
struct DemoApp: App {
    var body: some Scene {
        WindowGroup {
            LGDemoGallery()
                .preferredColorScheme(.dark) // 深色下玻璃观感最佳
        }
    }
}
```

每个组件文件内嵌 `#Preview`，可直接在 Xcode Canvas 中单独预览。

## 7. 性能与注意事项

1. **玻璃层级**：避免玻璃套玻璃超过两层。多层嵌套会在新系统触发不必要的离屏渲染，旧系统则高光叠加发灰。
2. **背景保障**：玻璃区域背后应有色彩/内容（推荐 `LGAmbientBackground` 或内容滚过）。纯色背景上玻璃质感大幅下降——这是材质特性，非缺陷。
3. **tint 用量**：`.lgGlass` 已将 tint 压至 0.35 不透明度，调用方不要再叠加更高不透明度的同名着色。
4. **列表性能**：长列表（>200 行）中的行项不建议整行玻璃；用 `.listStyle(.plain)` + 行内局部玻璃元素（如右侧按钮），或直接使用 iOS 26 原生 `List`（系统自带玻璃行）。
5. **阴影预算**：降级路径自带双层投影；深色模式下投影不可见属正常，浅色模式下勿再叠加额外阴影。
