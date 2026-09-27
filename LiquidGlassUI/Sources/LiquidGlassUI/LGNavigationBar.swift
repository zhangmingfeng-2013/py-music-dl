//
//  LGNavigationBar.swift
//  LiquidGlassUI
//
//  液态玻璃导航栏：标题 + 可选副标题 + 尾部操作区。
//  与滚动内容配合时，内容滚动到栏下方会自动透出折射感。
//

import SwiftUI

public struct LGNavigationBar<Actions: View>: View {

    public var title: String
    public var subtitle: String?
    @ViewBuilder public var actions: Actions

    public init(
        _ title: String,
        subtitle: String? = nil,
        @ViewBuilder actions: () -> Actions
    ) {
        self.title = title
        self.subtitle = subtitle
        self.actions = actions()
    }

    public var body: some View {
        HStack(spacing: LGSpacing.sm) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.headline)
                    .lineLimit(1)
                if let subtitle {
                    Text(subtitle)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: LGSpacing.sm)
            actions
                .labelStyle(.iconOnly)
                .buttonStyle(.lgGlass)
                .controlSize(.small)
        }
        .padding(.horizontal, LGSpacing.md)
        .padding(.vertical, LGSpacing.xs)
        .lgGlass(.regular, in: LGRadius.rect(LGRadius.large))
        .padding(.horizontal, LGSpacing.md)
    }
}

public extension LGNavigationBar where Actions == EmptyView {
    /// 无操作区版本
    init(_ title: String, subtitle: String? = nil) {
        self.title = title
        self.subtitle = subtitle
        self.actions = EmptyView()
    }
}

#Preview("导航栏") {
    ZStack {
        LGAmbientBackground()
        VStack {
            LGNavigationBar("音乐", subtitle: "资料库 · 8,432 首") {
                Button { } label: { Label("搜索", systemImage: "magnifyingglass") }
                Button { } label: { Label("更多", systemImage: "ellipsis") }
            }
            Spacer()
        }
        .padding(.top)
    }
    .preferredColorScheme(.dark)
}
