//
//  LGTextField.swift
//  LiquidGlassUI
//
//  液态玻璃输入框：支持前置图标、聚焦态高亮描边、提交回调。
//

import SwiftUI

public struct LGTextField: View {

    @Binding public var text: String
    public var placeholder: String
    public var systemImage: String?
    public var submitLabel: SubmitLabel
    public var onSubmit: (() -> Void)?

    @FocusState private var focused: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    public init(
        _ placeholder: String,
        text: Binding<String>,
        systemImage: String? = nil,
        submitLabel: SubmitLabel = .done,
        onSubmit: (() -> Void)? = nil
    ) {
        self.placeholder = placeholder
        self._text = text
        self.systemImage = systemImage
        self.submitLabel = submitLabel
        self.onSubmit = onSubmit
    }

    public var body: some View {
        HStack(spacing: LGSpacing.xs) {
            if let systemImage {
                Image(systemName: systemImage)
                    .font(.body)
                    .foregroundStyle(focused ? Color.accentColor : .secondary)
                    .symbolEffect(.bounce, value: focused)
                    .accessibilityHidden(true)
            }
            TextField(placeholder, text: $text)
                .textFieldStyle(.plain)
                .focused($focused)
                .submitLabel(submitLabel)
                .onSubmit { onSubmit?() }
        }
        .padding(.horizontal, LGSpacing.md)
        .padding(.vertical, LGSpacing.sm)
        .lgGlass(.regular, in: LGRadius.rect(LGRadius.medium))
        // 聚焦态：叠加一圈 tint 描边，模拟光线汇聚
        .overlay {
            LGRadius.rect(LGRadius.medium)
                .strokeBorder(Color.accentColor.opacity(focused ? 0.85 : 0), lineWidth: 1.5)
                .animation(
                    LGMotion.adaptive(LGMotion.smooth, reduceMotion: reduceMotion),
                    value: focused
                )
        }
        .contentShape(LGRadius.rect(LGRadius.medium))
        .onTapGesture { focused = true }
    }
}

#Preview("输入框") {
    struct Host: View {
        @State var q = ""
        var body: some View {
            ZStack {
                LGAmbientBackground()
                VStack(spacing: LGSpacing.md) {
                    LGTextField("搜索歌曲、歌手…", text: $q, systemImage: "magnifyingglass", submitLabel: .search)
                    LGTextField("输入邮箱", text: $q, systemImage: "envelope")
                }
                .padding()
            }
            .preferredColorScheme(.dark)
        }
    }
    return Host()
}
