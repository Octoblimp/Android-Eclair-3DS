from a3ds_paths import A3DS_ROOT
import sys
with open(f'{A3DS_ROOT}/third_party/frameworks/base/libs/ui/Surface.cpp', 'r') as f:
    content = f.read()

old_content = '''    const sp<GraphicBuffer>& backBuffer(mBuffers[bufIdx]);
    if (backBuffer == 0 || 
        ((uint32_t(backBuffer->usage) & usage) != usage) ||
        mSharedBufferClient->needNewBuffer(bufIdx)) 
    {'''

new_content = '''    const sp<GraphicBuffer>& backBuffer(mBuffers[bufIdx]);
    bool needNewBuffer = mSharedBufferClient->needNewBuffer(bufIdx);
    if (backBuffer == 0 || 
        ((uint32_t(backBuffer->usage) & usage) != usage) ||
        needNewBuffer) 
    {'''

if old_content in content:
    content = content.replace(old_content, new_content)
    with open(f'{A3DS_ROOT}/third_party/frameworks/base/libs/ui/Surface.cpp', 'w') as f:
        f.write(content)
    print('Patch applied successfully')
else:
    print('Old content not found')
