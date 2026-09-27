//
//  LGCard.swift
//  LiquidGlassUI
//
//  液态玻璃卡片容器：内容分组的基础表面，支持悬停浮起（macOS/指针设备）。
//

import SwiftUI

public struct LGCard<Content: View>: View {

    public var padding: CGFloat
    public var radius: CGFloat
    public var tint: Color?
    /// 开启后指针悬停时轻微浮起并提亮（macOS / iPad 指针）
    public var hoverable: Bool
    @ViewBuilder public var content: Content

    @State private var isHovered = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    public init(
        padding: CGFloat = LGSpacing.md,
        radius: CGFloat = LGRadius.large,
        tint: Color? = nil,
        hoverable: Bool = false,
        @ViewBuilder content: () -> Content
    ) {
        self.padding = padding
        self.radius = radius
        self.tint = tint
        self.hoverable = hoverable
        self.content = content()
    }

    public var body: some View {
        content
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .lgGlass(.regular, in: LGRadius.rect(radius), tint: tint)
            .scaleEffect(isHovered ? 1.012 : 1)
            .brightness(isHovered ? 0.03 : 0)
            .animation(
                LGMotion.adaptive(LGMotion.smooth, reduceMotion: reduceMotion),
                value: isHovered
            )
            .onHover { hovering in
                guard hoverable else { return }
                isHovered = hovering
            }
    }
}

#Preview("卡片") {
    ZStack {
        LGAmbientBackground()
        VStack(spacing: LGSpacing.md) {
            LGCard(hoverable: true) {
                VStack(alignment: .leading, spacing: LGSpacing.xs) {
                    Label("每日推荐", systemImage: "sparkles")
                        .font(.headline)
                    Text("根据你的收听习惯生成的 30 首歌曲。")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }
            LGCard(tint: .blue) {
                HStack {
                    Image(systemName: "airpodspro")
                        .font(.title2)
                    VStack(alignment: .leading) {
                        Text("AirPods Pro").font(.headline)
                        Text("已连接 · 电量 82%").font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer()
                }
            }
        }
        .padding()
    }
    .preferredColorScheme(.dark)
}
