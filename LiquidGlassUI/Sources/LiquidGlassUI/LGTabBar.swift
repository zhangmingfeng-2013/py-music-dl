//
//  LGTabBar.swift
//  LiquidGlassUI
//
//  液态玻璃标签栏：悬浮胶囊形态，选中项玻璃高亮并平滑迁移（morphing）。
//  新系统可升级为原生 Tab + .tabBarMinimizeBehavior(.onScrollDown)。
//

import SwiftUI

public struct LGTabItem: Hashable, Identifiable {
    public let id: String
    public let title: String
    public let systemImage: String

    public init(id: String, title: String, systemImage: String) {
        self.id = id
        self.title = title
        self.systemImage = systemImage
    }
}

public struct LGTabBar: View {

    @Binding public var selection: String
    public var items: [LGTabItem]

    @Namespace private var glassNamespace
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    public init(selection: Binding<String>, items: [LGTabItem]) {
        self._selection = selection
        self.items = items
    }

    public var body: some View {
        HStack(spacing: LGSpacing.xxs) {
            ForEach(items) { item in
                tabButton(for: item)
            }
        }
        .padding(LGSpacing.xxs)
        .lgGlass(.regular, in: Capsule())
        .shadow(color: .black.opacity(0.15), radius: 12, x: 0, y: 6)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("标签栏")
    }

    @ViewBuilder
    private func tabButton(for item: LGTabItem) -> some View {
        let selected = selection == item.id
        Button {
            withAnimation(LGMotion.adaptive(LGMotion.morph, reduceMotion: reduceMotion)) {
                selection = item.id
            }
        } label: {
            HStack(spacing: LGSpacing.xxs) {
                Image(systemName: item.systemImage)
                    .font(.callout.weight(.medium))
                    .contentTransition(.symbolEffect(.replace))
                if selected {
                    Text(item.title)
                        .font(.callout.weight(.medium))
                        .transition(.opacity.combined(with: .blurReplace))
                }
            }
            .padding(.horizontal, selected ? LGSpacing.md : LGSpacing.sm + LGSpacing.xxs)
            .padding(.vertical, LGSpacing.xs)
            .foregroundStyle(selected ? .primary : .secondary)
            .background {
                if selected {
                    // 选中胶囊：随选中项在标签间平滑迁移
                    if #available(macOS 26.0, iOS 26.0, *) {
                        Capsule()
                            .fill(.clear)
                            .glassEffect(.regular.interactive(), in: .capsule)
                            .glassEffectID(item.id, in: glassNamespace)
                    } else {
                        Capsule()
                            .fill(.white.opacity(0.22))
                            .matchedGeometryEffect(id: item.id, in: glassNamespace)
                    }
                }
            }
        }
        .buttonStyle(.plain)
        .accessibilityLabel(item.title)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

#Preview("标签栏") {
    struct Host: View {
        @State var tab = "home"
        let items = [
            LGTabItem(id: "home", title: "首页", systemImage: "house"),
            LGTabItem(id: "browse", title: "浏览", systemImage: "square.grid.2x2"),
            LGTabItem(id: "radio", title: "电台", systemImage: "dot.radiowaves.left.and.right"),
            LGTabItem(id: "library", title: "资料库", systemImage: "music.note.list"),
        ]
        var body: some View {
            ZStack {
                LGAmbientBackground()
                VStack {
                    Spacer()
                    LGTabBar(selection: $tab, items: items)
                        .padding(.bottom, LGSpacing.xl)
                }
            }
            .preferredColorScheme(.dark)
        }
    }
    return Host()
}
