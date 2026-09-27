//
//  LGTheme.swift
//  LiquidGlassUI
//
//  设计令牌（Design Tokens）与液态玻璃材质兼容层。
//  所有组件仅引用此文件中的令牌，不硬编码数值，保证全局一致性。
//

import SwiftUI

// MARK: - 间距令牌（4pt 网格）

public enum LGSpacing {
    public static let xxs: CGFloat = 4
    public static let xs: CGFloat = 8
    public static let sm: CGFloat = 12
    public static let md: CGFloat = 16
    public static let lg: CGFloat = 20
    public static let xl: CGFloat = 24
    public static let xxl: CGFloat = 32
}

// MARK: - 圆角令牌（连续圆角 continuous corner）

public enum LGRadius {
    /// 小元素：标签、徽标
    public static let small: CGFloat = 10
    /// 输入框、按钮（非胶囊形态）
    public static let medium: CGFloat = 16
    /// 卡片
    public static let large: CGFloat = 22
    /// 大型容器、弹窗
    public static let xlarge: CGFloat = 28

    /// 连续圆角矩形（Apple 标志性的 squircle 观感）
    public static func rect(_ radius: CGFloat) -> RoundedRectangle {
        RoundedRectangle(cornerRadius: radius, style: .continuous)
    }
}

// MARK: - 动效令牌

public enum LGMotion {
    /// 状态过渡（悬停、选中、展开）
    public static let smooth = Animation.smooth(duration: 0.35)
    /// 按压回弹
    public static let press = Animation.spring(response: 0.32, dampingFraction: 0.72)
    /// 玻璃形态切换（morphing）
    public static let morph = Animation.smooth(duration: 0.45)
    /// 按压缩放比例
    public static let pressScale: CGFloat = 0.97

    /// 遵循「减弱动态效果」辅助设置：开启时移除位移动画，仅保留淡入淡出
    public static func adaptive(_ animation: Animation, reduceMotion: Bool) -> Animation {
        reduceMotion ? .easeOut(duration: 0.15) : animation
    }
}

// MARK: - 液态玻璃材质（兼容层）

/// 玻璃形态枚举：映射原生 Glass 变体；旧系统忽略差异，统一材质模拟。
public enum LGGlassVariant {
    /// 常规磨砂（默认，适用于绝大多数表面）
    case regular
    /// 更通透（适用于内容已经较暗/较纯的背景上）
    case clear
}

/// 统一玻璃修饰符：macOS 26 / iOS 26+ 使用原生 .glassEffect，
/// 更早系统使用 ultraThinMaterial + 顶部高光描边 + 环境投影模拟。
struct LGGlassModifier: ViewModifier {
    var variant: LGGlassVariant
    var tint: Color?
    var interactive: Bool
    var shape: AnyShape

    func body(content: Content) -> some View {
        if #available(macOS 26.0, iOS 26.0, *) {
            content.glassEffect(nativeGlass, in: shape)
        } else {
            legacyBody(content: content)
        }
    }

    /// 原生 Glass 构造（仅新系统编译路径可达）
    @available(macOS 26.0, iOS 26.0, *)
    private var nativeGlass: Glass {
        var glass: Glass = (variant == .clear) ? .clear : .regular
        if let tint {
            // tint 保持低不透明：玻璃应透出内容色，着色只是倾向性
            glass = glass.tint(tint.opacity(0.35))
        }
        if interactive {
            glass = glass.interactive()
        }
        return glass
    }

    /// 旧系统降级实现：材质底 + 上缘高光 + 内描边 + 柔和投影
    @ViewBuilder
    private func legacyBody(content: Content) -> some View {
        content
            .background {
                ZStack {
                    shape.fill(.ultraThinMaterial)
                    if let tint {
                        shape.fill(tint.opacity(0.10))
                    }
                    // 顶部渐变高光：模拟光源从上方照射玻璃边缘
                    shape.fill(
                        LinearGradient(
                            colors: [.white.opacity(0.28), .white.opacity(0.06), .clear],
                            startPoint: .top,
                            endPoint: .center
                        )
                    )
                    shape.stroke(
                        LinearGradient(
                            colors: [.white.opacity(0.55), .white.opacity(0.12)],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        ),
                        lineWidth: 1
                    )
                }
            }
            .shadow(color: .black.opacity(0.18), radius: 18, x: 0, y: 8)
            .shadow(color: .black.opacity(0.08), radius: 4, x: 0, y: 2)
    }
}

public extension View {
    /// 为视图应用液态玻璃表面。
    /// - Parameters:
    ///   - variant: 玻璃变体（regular / clear）
    ///   - shape: 玻璃外形，默认胶囊；卡片请传 LGRadius.rect(.large)
    ///   - tint: 倾向性着色（自动压低不透明度，保持通透）
    ///   - interactive: 是否响应悬停/触摸的提亮与弹性（按钮类建议开启）
    func lgGlass(
        _ variant: LGGlassVariant = .regular,
        in shape: some Shape = Capsule(),
        tint: Color? = nil,
        interactive: Bool = false
    ) -> some View {
        modifier(LGGlassModifier(
            variant: variant,
            tint: tint,
            interactive: interactive,
            shape: AnyShape(shape)
        ))
    }
}

// MARK: - 演示背景（玻璃需要有内容在背后才能体现折射感）

/// 演示/推荐使用的氛围背景：多层柔和渐变光斑，供玻璃表面折射。
public struct LGAmbientBackground: View {
    public var colors: [Color]
    public init(colors: [Color] = [.blue, .purple, .pink, .orange]) {
        self.colors = colors
    }

    public var body: some View {
        TimelineView(.animation) { context in
            let t = context.date.timeIntervalSinceReferenceDate
            Canvas { ctx, size in
                ctx.fill(Rectangle().path(in: CGRect(origin: .zero, size: size)),
                         with: .color(.black.opacity(0.92)))
                for (i, color) in colors.enumerated() {
                    let phase = t * 0.25 + Double(i) * 1.7
                    let cx = size.width  * (0.5 + 0.38 * cos(phase))
                    let cy = size.height * (0.5 + 0.38 * sin(phase * 0.9))
                    let r  = min(size.width, size.height) * 0.55
                    let rect = CGRect(x: cx - r / 2, y: cy - r / 2, width: r, height: r)
                    ctx.fill(
                        Ellipse().path(in: rect),
                        with: .radialGradient(
                            Gradient(colors: [color.opacity(0.55), .clear]),
                            center: CGPoint(x: cx, y: cy),
                            startRadius: 0,
                            endRadius: r / 2
                        )
                    )
                }
            }
        }
        .ignoresSafeArea()
        .accessibilityHidden(true)
    }
}

#Preview("氛围背景") {
    LGAmbientBackground()
}
