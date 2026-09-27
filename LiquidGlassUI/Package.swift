// swift-tools-version: 6.0
import PackageDescription

/// LiquidGlassUI — Apple Liquid Glass 设计语言的 SwiftUI 组件库。
/// 部署目标 macOS 14 / iOS 17：新系统（macOS 26 / iOS 26+）走原生 .glassEffect，
/// 旧系统自动降级为材质模拟实现，调用方无感知。
let package = Package(
    name: "LiquidGlassUI",
    platforms: [
        .macOS(.v14),
        .iOS(.v17)
    ],
    products: [
        .library(name: "LiquidGlassUI", targets: ["LiquidGlassUI"])
    ],
    targets: [
        .target(name: "LiquidGlassUI", path: "Sources/LiquidGlassUI")
    ]
)
