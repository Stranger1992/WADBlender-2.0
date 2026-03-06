"""
WAD2 Chunk Identifiers
Based on Tomb Editor's Wad2Chunks.cs
"""

class ChunkId:
    """WAD2 chunk type identifiers"""

    # Root level chunks
    SuggestedGameVersion = b'W2SuggestedGameVersion'
    SoundSystem = b'W2SoundSystem'
    Metadata = b'W2Metadata'

    # Texture chunks
    Textures = b'W2Textures'
    Txt = b'W2Txt'
    TxtIndex = b'W2TxtIndex'
    TxtData = b'W2TxtData'
    TxtName = b'W2TxtName'
    TxtRelPath = b'W2TxtRelPath'

    # Sample chunks
    Samples = b'W2Samples'
    Smp = b'W2Smp'
    SmpIndex = b'W2SmpIndex'
    SmpData = b'W2SmpData'
    SmpFilenameObsolete = b'W2SmpFilenameObsolete'

    # Sound info chunks
    SoundInfos = b'W2SoundInfos'
    SoundInfo = b'W2SoundInfo'
    SoundInfoName = b'W2SoundInfoName'
    SoundInfoIndex = b'W2SoundInfoIndex'
    SoundInfoVolume = b'W2SoundInfoVolume'
    SoundInfoRange = b'W2SoundInfoRange'
    SoundInfoPitch = b'W2SoundInfoPitch'
    SoundInfoChance = b'W2SoundInfoChance'
    SoundInfoDisablePanning = b'W2SoundInfoDisablePanning'
    SoundInfoRandomizePitch = b'W2SoundInfoRandomizePitch'
    SoundInfoRandomizeVolume = b'W2SoundInfoRandomizeVolume'
    SoundInfoLoopBehaviour = b'W2SoundInfoLoopBehaviour'
    SoundInfoSampleRate = b'W2SoundInfoSampleRate'
    SoundInfoSamples = b'W2SoundInfoSamples'

    # Mesh chunks (verbose names from read_wad2.py - for reading compatibility)
    Meshes = b'W2Meshes'
    Mesh = b'W2Mesh'
    MeshPositions = b'W2MeshPositions'
    MeshNormals = b'W2MeshNormals'
    MeshShades = b'W2MeshShades'
    MeshColors = b'W2MeshColors'
    MeshVertexAttributes = b'W2MeshVertexAttributes'
    MeshVertexWeights = b'W2MeshVertexWeights'
    MeshPolygons = b'W2MeshPolygons'
    MeshTriangles = b'W2MeshTriangles'
    MeshQuads = b'W2MeshQuads'
    MeshPolygonIndices = b'W2MeshPolygonIndices'
    MeshPolygonTextureCoordinates = b'W2MeshPolygonTextureCoordinates'
    MeshSphere = b'W2MeshSphere'
    MeshBBox = b'W2MeshBBox'
    MeshLightingType = b'W2MeshLightingType'
    MeshName = b'W2MeshName'

    # Mesh chunks (official names from Wad2Chunks.cs - for writing)
    MeshIndex = b'W2Index'
    MeshVertexPositions = b'W2VrtPos'
    MeshVertexPosition = b'W2Pos'
    MeshVertexNormals = b'W2VrtNorm'
    MeshVertexNormal = b'W2N'
    MeshVertexShades = b'W2VrtShd'
    MeshVertexColor = b'W2VxCol'
    MeshVertexAttr = b'W2VrtAttr'
    MeshVertexAttribute = b'W2VxAttr'
    MeshBoundingBox = b'W2BBox'

    # Sprite chunks
    Sprites = b'W2Sprites'
    Sprite = b'W2Sprite'
    SpriteIndex = b'W2SpriteIndex'
    SpriteTexture = b'W2SpriteTexture'
    SpriteAlignment = b'W2SpriteAlignment'

    # Sprite sequence chunks
    SpriteSequences = b'W2SpriteSequences'
    SpriteSequence = b'W2SpriteSequence'
    SpriteSequenceIndex = b'W2SpriteSequenceIndex'
    SpriteSequenceSprite = b'W2SpriteSequenceSprite'

    # Moveable chunks
    Moveables = b'W2Moveables'
    Moveable = b'W2Moveable'
    MoveableId = b'W2MoveableId'
    MoveableMeshes = b'W2MoveableMeshes'
    MoveableSkin = b'W2MoveableSkin'
    MoveableBones = b'W2MoveableBones'
    MoveableBone = b'W2MoveableBone'
    MoveableBoneName = b'W2MoveableBoneName'
    MoveableBoneParent = b'W2MoveableBoneParent'
    MoveableBoneTranslation = b'W2MoveableBoneTranslation'
    MoveableBoneMesh = b'W2MoveableBoneMesh'
    MoveableAnimations = b'W2MoveableAnimations'

    # Animation chunks
    Animation = b'W2Animation'
    AnimationObsolete = b'W2Anm'
    AnimationCompact = b'W2Ani'
    AnimationName = b'W2AnimationName'
    AnimationKeyFrames = b'W2AnimationKeyFrames'
    AnimationKeyFrame = b'W2AnimationKeyFrame'
    AnimationKeyFrameBBox = b'W2AnimationKeyFrameBBox'
    AnimationKeyFrameOffset = b'W2AnimationKeyFrameOffset'
    AnimationKeyFrameAngles = b'W2AnimationKeyFrameAngles'
    AnimationFrameRate = b'W2AnimationFrameRate'
    AnimationStateId = b'W2AnimationStateId'
    AnimationEndFrame = b'W2AnimationEndFrame'
    AnimationNextAnimation = b'W2AnimationNextAnimation'
    AnimationNextFrame = b'W2AnimationNextFrame'
    AnimationStateChanges = b'W2AnimationStateChanges'
    AnimationStateChange = b'W2AnimationStateChange'
    AnimationDispatches = b'W2AnimationDispatches'
    AnimationDispatch = b'W2AnimationDispatch'
    AnimationCommands = b'W2AnimationCommands'
    AnimationCommand = b'W2AnimationCommand'
    AnimationVelocity = b'W2AnimationVelocity'
    AnimationAcceleration = b'W2AnimationAcceleration'
    AnimationFrameDuration = b'W2AnimationFrameDuration'

    # Static chunks
    Statics = b'W2Statics'
    Static = b'W2Static'
    StaticId = b'W2StaticId'
    StaticMesh = b'W2StaticMesh'
    StaticVisibilityBox = b'W2StaticVisibilityBox'
    StaticCollisionBox = b'W2StaticCollisionBox'
    StaticAmbientLight = b'W2StaticAmbientLight'
    StaticLights = b'W2StaticLights'
    StaticLight = b'W2StaticLight'

    # Animated texture sets
    AnimatedTextureSets = b'W2AnimatedTextureSets'
    AnimatedTextureSet = b'W2AnimatedTextureSet'
    AnimatedTextureSetName = b'W2AnimatedTextureSetName'
    AnimatedTextureSetType = b'W2AnimatedTextureSetType'
    AnimatedTextureSetFrames = b'W2AnimatedTextureSetFrames'

    # ==== ABBREVIATED/COMPACT CHUNK IDS ====
    # Some WAD2 files use shortened chunk IDs for space efficiency
    # These are alternative identifiers for the same data

    # Mesh compact chunks
    MeshVrtPos = b'W2VrtPos'  # Vertex positions (compact)
    MeshVrtNorm = b'W2VrtNorm'  # Vertex normals (compact)
    MeshVrtShd = b'W2VrtShd'  # Vertex shades (compact)
    MeshVrtAttr = b'W2VrtAttr'  # Vertex attributes (compact)
    MeshVrtWghts = b'W2VrtWghts'  # Vertex weights (compact)
    MeshPolys = b'W2Polys'  # Polygons (compact)
    MeshTri2 = b'W2Tr2'  # Triangles (compact)
    MeshQuad2 = b'W2Uq2'  # Quads (compact)
    MeshTri = b'W2Tr'  # Triangles (compact v1)
    MeshQuad = b'W2Uq'  # Quads (compact v1)
    MeshSphC = b'W2SphC'  # Sphere center (compact)
    MeshSphR = b'W2SphR'  # Sphere radius (compact)
    MeshBBMin = b'W2BBMin'  # Bounding box min (compact)
    MeshBBMax = b'W2BBMax'  # Bounding box max (compact)
    MeshVisible = b'W2MeshVisible'  # Mesh visibility flag
    MeshN = b'W2N'  # Normals (ultra-compact)
    MeshPos = b'W2Pos'  # Positions (ultra-compact)

    # Bone compact chunks
    Bone2 = b'W2Bone2'  # Bone (compact)
    BoneMesh = b'W2BoneMesh'  # Bone mesh index (compact)
    BoneTrans = b'W2BoneTrans'  # Bone translation (compact)

    # Animation compact chunks
    Ani2 = b'W2Ani2'  # Animation (compact)
    AniV = b'W2AniV'  # Animation velocity (compact)
    AnmName = b'W2AnmName'  # Animation name (compact)
    Kf = b'W2Kf'  # Keyframe (compact)
    KfA = b'W2KfA'  # Keyframe angles (compact)
    KfOffs = b'W2KfOffs'  # Keyframe offset (compact)
    KfBB = b'W2KfBB'  # Keyframe bounding box (compact)

    # Static compact chunks
    Static2 = b'W2Static2'  # Static (compact)

    # Other compact chunks
    Index = b'W2Index'  # Generic index
    BBox = b'W2BBox'  # Bounding box
    StCh = b'W2StCh'  # State change (compact)
    Disp = b'W2Disp'  # Dispatch (compact)
    Cmd = b'W2Cmd'    # Command (legacy compact) — TombLib AnimCommand
    Cmd2 = b'W2Cmd2'  # Command (compact) — TombLib AnimCommand2
    CmdSnd = b'W2CmdSnd'  # Sound command (compact)
