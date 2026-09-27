//
//  LGButton.swift
//  LiquidGlassUI
//
//  液态玻璃按钮样式：standard（透明玻璃）/ prominent（着色显著）/ plain（无边框文字）。
//

import SwiftUI

public struct LGGlassButtonStyle: ButtonStyle {

    public enum Prominence: Sendable {
        /// 透明玻璃胶囊，次级/常规操作
        case standard
        /// tint 着色玻璃，当前场景主操作（一屏不超过一个）
        case prominent
        /// 无玻璃底，仅文字，三级操作
        case plain
    }

    public var prominence: Prominence
    public var tint: Color
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.isEnabled) private var isEnabled

    public init(prominence: Prominence = .standard, tint: Color = .accentColor) {
        self.prominence = prominence
        self.tint = tint
    }

    public func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.body.weight(.medium))
            .padding(.horizontal, LGSpacing.lg)
            .padding(.vertical, LGSpacing.sm)
            .foregroundStyle(foregroundColor)
            .background { background }
            .scaleEffect(configuration.isPressed && prominence != .plain ? LGMotion.pressScale : 1)
            .opacity(configuration.isPressed ? 0.88 : 1)
            .opacity(isEnabled ? 1 : 0.45)
            .animation(
                LGMotion.adaptive(LGMotion.press, reduceMotion: reduceMotion),
                value: configuration.isPressed
            )
    }

    @ViewBuilder
    private var background: some View {
        switch prominence {
        case .standard:
            Capsule()
                .fill(Color.clear)
                .lgGlass(.regular, interactive: true)
        case .prominent:
            Capsule()
                .fill(Color.clear)
                .lgGlass(.regular, tint: tint, interactive: true)
        case .plain:
            EmptyView()
        }
    }

    private var foregroundColor: Color {
        switch prominence {
        case .prominent: return .white
        case .standard:  return .primary
        case .plain:     return tint
        }
    }
}

public extension ButtonStyle where Self == LGGlassButtonStyle {
    /// 透明玻璃按钮
    static var lgGlass: LGGlassButtonStyle { LGGlassButtonStyle() }
    /// 着色显著按钮（主操作）
    static func lgGlassProminent(tint: Color = .accentColor) -> LGGlassButtonStyle {
        LGGlassButtonStyle(prominence: .prominent, tint: tint)
    }
    /// 无边框文字按钮
    static var lgPlain: LGGlassButtonStyle { LGGlassButtonStyle(prominence: .plain) }
}

#Preview("按钮") {
    ZStack {
        LGAmbientBackground()
        VStack(spacing: LGSpacing.lg) {
            Button("常规操作") {}.buttonStyle(.lgGlass)
            Button("主操作") {}.buttonStyle(.lgGlassProminent(tint: .blue))
            Button("文字操作") {}.buttonStyle(.lgPlain)
            Button("禁用态") {}.buttonStyle(.lgGlass).disabled(true)
        }
        .padding()
    }
    .preferredColorScheme(.dark)
}
