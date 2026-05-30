import dmgbuild

# 创建 DMG 配置
settings = {
    'format': 'UDZO',
    'compression_level': 6,
    'files': [
        ('build/exe.macosx-10.15-universal2-3.14/MusicDownloader', 'MusicDownloader'),
    ],
    'symlinks': {'Applications': '/Applications'},
    'window': {
        'position': (100, 100),
        'size': (500, 400),
    },
    'background': None,
    'icon-size': 128,
    'icon_locations': {
        'MusicDownloader': (150, 200),
        'Applications': (350, 200),
    },
}

# 生成 DMG
dmgbuild.build_dmg(
    'dist/MusicDownloader.dmg',
    'MusicDownloader',
    settings=settings,
)
