//
//  LGDemoGallery.swift
//  LiquidGlassUI
//
//  演示画廊：组件库全部元素的真实场景组合。
//  在 Xcode 中新建 App 工程、依赖本包后，将根视图设为 LGDemoGallery() 即可运行。
//  本文件自带 #Preview，直接在 Xcode Canvas 中预览亦可。
//

import SwiftUI

public struct LGDemoGallery: View {

    @State private var tab = "home"
    @State private var query = ""
    @State private var chips: [Bool] = [true, false, false, false]
    @State private var toast = false

    private let tabs = [
        LGTabItem(id: "home", title: "首页", systemImage: "house"),
        LGTabItem(id: "browse", title: "浏览", systemImage: "square.grid.2x2"),
        LGTabItem(id: "library", title: "资料库", systemImage: "music.note.list"),
    ]
    private let chipTitles = ["全部", "流行", "古典", "播客"]

    public init() {}

    public var body: some View {
        ZStack {
            LGAmbientBackground()

            ScrollView {
                VStack(spacing: LGSpacing.md) {
                    LGNavigationBar("音乐", subtitle: "Liquid Glass 组件画廊") {
                        Button { } label: { Label("设置", systemImage: "gear") }
                    }

                    LGTextField("搜索歌曲、歌手…", text: $query, systemImage: "magnifyingglass", submitLabel: .search)

                    // 筛选 Chips
                    HStack(spacing: LGSpacing.xs) {
                        ForEach(chipTitles.indices, id: \.self) { i in
                            LGChip(chipTitles[i], isSelected: chipBinding(at: i))
                        }
                        Spacer()
                    }
                    .padding(.horizontal, LGSpacing.md)

                    // 按钮组
                    LGCard {
                        VStack(alignment: .leading, spacing: LGSpacing.sm) {
                            Text("按钮 / Buttons").font(.headline)
                            HStack(spacing: LGSpacing.sm) {
                                Button("常规") {}.buttonStyle(.lgGlass)
                                Button("主操作") { toast = true }.buttonStyle(.lgGlassProminent(tint: .blue))
                                Button("文字") {}.buttonStyle(.lgPlain)
                            }
                        }
                    }

                    // 卡片组
                    LGCard(hoverable: true) {
                        HStack(spacing: LGSpacing.md) {
                            RoundedRectangle(cornerRadius: LGRadius.small, style: .continuous)
                                .fill(LinearGradient(colors: [.pink, .orange], startPoint: .topLeading, endPoint: .bottomTrailing))
                                .frame(width: 56, height: 56)
                                .overlay { Image(systemName: "music.note").foregroundStyle(.white) }
                            VStack(alignment: .leading, spacing: 2) {
                                Text("玻璃卡片 / Card").font(.headline)
                                Text("悬停浮起 · 连续圆角 · 折射背景").font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Image(systemName: "chevron.right").foregroundStyle(.secondary)
                        }
                    }
                    .onTapGesture { toast = true }

                    Color.clear.frame(height: 120) // 底部 Tab 悬浮区留白
                }
                .padding(.horizontal, LGSpacing.md)
                .padding(.top, LGSpacing.sm)
            }
        }
        // 底部悬浮标签栏
        .safeAreaInset(edge: .bottom) {
            LGTabBar(selection: $tab, items: tabs)
                .padding(.bottom, LGSpacing.xs)
        }
        // 顶部 Toast（玻璃通知条）
        .overlay(alignment: .top) {
            if toast {
                Label("已加入播放队列", systemImage: "checkmark.circle.fill")
                    .font(.subheadline.weight(.medium))
                    .padding(.horizontal, LGSpacing.lg)
                    .padding(.vertical, LGSpacing.sm)
                    .lgGlass(.regular, tint: .green)
                    .padding(.top, LGSpacing.xl)
                    .transition(.move(edge: .top).combined(with: .opacity))
                    .onAppear {
                        DispatchQueue.main.asyncAfter(deadline: .now() + 1.6) {
                            withAnimation(LGMotion.smooth) { toast = false }
                        }
                    }
            }
        }
        .animation(LGMotion.smooth, value: toast)
    }

    /// 将 chips 数组映射为互斥单选 Binding
    private func chipBinding(at index: Int) -> Binding<Bool> {
        Binding(
            get: { chips[index] },
            set: { _ in
                for i in chips.indices { chips[i] = (i == index) }
            }
        )
    }
}

#Preview("组件画廊") {
    LGDemoGallery()
        .preferredColorScheme(.dark)
}
