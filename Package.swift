// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "Dictation",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .executable(name: "Dictation", targets: ["Dictation"])
    ],
    targets: [
        .executableTarget(
            name: "Dictation",
            path: "Dictation",
            exclude: ["Info.plist", "Dictation.entitlements"],
            linkerSettings: [
                .linkedFramework("Cocoa"),
                .linkedFramework("AVFoundation"),
                .linkedFramework("Carbon")
            ]
        )
    ]
)
