//
//  LGChip.swift
//  LiquidGlassUI
//
//  液态玻璃筛选标签（Chip）：单选/多选过滤场景，选中态着色玻璃。
//

import SwiftUI

public struct LGChip: View {

    @Binding public var isSelected: Bool
    public var title: String
    public var systemImage: String?
    public var tint: Color

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    public init(
        _ title: String,
        isSelected: Binding<Bool>,
        systemImage: String? = nil,
        tint: Color = .accentColor
    ) {
        self.title = title
        self._isSelected = isSelected
        self.systemImage = systemImage
        self.tint = tint
    }

    public var body: some View {
        Button {
            withAnimation(LGMotion.adaptive(LGMotion.press, reduceMotion: reduceMotion)) {
                isSelected.toggle()
            }
        } label: {
            HStack(spacing: LGSpacing.xxs) {
                if let systemImage {
                    Image(systemName: systemImage)
                        .font(.caption.weight(.medium))
                }
                Text(title)
                    .font(.subheadline.weight(.medium))
            }
            .padding(.horizontal, LGSpacing.md)
            .padding(.vertical, LGSpacing.xs)
            .foregroundStyle(isSelected ? .white : .secondary)
            .background {
                if isSelected {
                    Capsule().fill(.clear).lgGlass(.regular, tint: tint, interactive: true)
                } else {
                    Capsule().fill(.clear).lgGlass(.clear)
                }
            }
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }
}

#Preview("筛选标签") {
    struct Host: View {
        @State var a = true
        @State var b = false
        @State var c = false
        var body: some View {
            ZStack {
                LGAmbientBackground()
                HStack(spacing: LGSpacing.xs) {
                    LGChip("全部", isSelected: $a, systemImage: "line.3.horizontal.decrease")
                    LGChip("已下载", isSelected: $b, tint: .green)
                    LGChip("收藏", isSelected: $c, systemImage: "heart", tint: .pink)
                }
                .padding()
            }
            .preferredColorScheme(.dark)
        }
    }
    return Host()
}
