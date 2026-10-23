// Minimal 32-bit d3d9 proxy for San11WPK.
//
// The game imports only Direct3DCreate9. We forward that to the real
// SysWOW64 d3d9.dll, then wait for the engine device pointer at
// San11WPK.exe+0x2ED6F74, patch the device vtable's SetTransform slot, and
// mirror D3DTS_VIEW/D3DTS_PROJECTION matrices into a named shared memory
// object "Local\\San11Camera". No game logic is called and no input is sent.
//
// Build (32-bit MinGW):
//   g++ -m32 -O2 -shared -static-libgcc -static-libstdc++ \
//       d3d9_proxy.cpp -o d3d9.dll -ld3d9 -lole32 -luuid
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d9.h>
#include <cstdint>
#include <cstring>

#pragma pack(push, 1)
struct CameraShared {
    volatile LONG version;
    DWORD view_sequence;
    DWORD projection_sequence;
    float view[16];
    float projection[16];
};
#pragma pack(pop)

static const wchar_t* kMappingName = L"Local\\San11Camera";
// DAT_06ED6F74 in the loaded game; image base 0x400000 => RVA 0x6AD6F74.
static const std::uintptr_t kDeviceGlobalRva = 0x6AD6F74;
static const int kSetTransformVtableIndex = 44;

typedef HRESULT(WINAPI* SetTransformFn)(IDirect3DDevice9*, D3DTRANSFORMSTATETYPE, const D3DMATRIX*);
static SetTransformFn g_real_set_transform = nullptr;
static CameraShared* g_shared = nullptr;
static volatile LONG g_patched = 0;
static DWORD g_view_seq = 0;
static DWORD g_projection_seq = 0;

static void copy_matrix(float* dst, const D3DMATRIX* matrix) {
    std::memcpy(dst, matrix, sizeof(float) * 16);
    InterlockedIncrement(&g_shared->version);
}

static HRESULT WINAPI hook_set_transform(
    IDirect3DDevice9* device,
    D3DTRANSFORMSTATETYPE state,
    const D3DMATRIX* matrix) {
    HRESULT result = g_real_set_transform(device, state, matrix);
    if (g_shared != nullptr && matrix != nullptr && SUCCEEDED(result)) {
        if (state == D3DTS_VIEW) {
            copy_matrix(g_shared->view, matrix);
            g_shared->view_sequence = ++g_view_seq;
        } else if (state == D3DTS_PROJECTION) {
            copy_matrix(g_shared->projection, matrix);
            g_shared->projection_sequence = ++g_projection_seq;
        }
    }
    return result;
}

static bool patch_device_vtable(void* device) {
    if (device == nullptr) return false;
    void** vtable = *reinterpret_cast<void***>(device);
    if (vtable == nullptr) return false;

    DWORD old_protect = 0;
    if (!VirtualProtect(&vtable[kSetTransformVtableIndex], sizeof(void*), PAGE_READWRITE, &old_protect)) {
        return false;
    }
    g_real_set_transform = reinterpret_cast<SetTransformFn>(vtable[kSetTransformVtableIndex]);
    vtable[kSetTransformVtableIndex] = reinterpret_cast<void*>(&hook_set_transform);
    DWORD ignored = 0;
    VirtualProtect(&vtable[kSetTransformVtableIndex], sizeof(void*), old_protect, &ignored);
    return g_real_set_transform != nullptr;
}

static DWORD WINAPI camera_thread(LPVOID) {
    HANDLE mapping = CreateFileMappingW(
        INVALID_HANDLE_VALUE, nullptr, PAGE_READWRITE, 0, sizeof(CameraShared), kMappingName);
    if (mapping == nullptr) return 1;
    g_shared = static_cast<CameraShared*>(MapViewOfFile(mapping, FILE_MAP_ALL_ACCESS, 0, 0, sizeof(CameraShared)));
    if (g_shared == nullptr) {
        CloseHandle(mapping);
        return 1;
    }
    std::memset(g_shared, 0, sizeof(*g_shared));

    HMODULE game = GetModuleHandleW(nullptr);
    if (game == nullptr) return 1;
    auto global = reinterpret_cast<void* volatile*>(
        reinterpret_cast<std::uintptr_t>(game) + kDeviceGlobalRva);

    for (;;) {
        void* device = *global;
        if (device != nullptr && InterlockedCompareExchange(&g_patched, 1, 0) == 0) {
            if (!patch_device_vtable(device)) {
                InterlockedExchange(&g_patched, 0);
            }
        }
        Sleep(50);
    }
    return 0;
}

extern "C" __declspec(dllexport) IDirect3D9* WINAPI Direct3DCreate9(UINT sdk_version) {
    static HMODULE real_d3d9 = nullptr;
    static decltype(&Direct3DCreate9) real_create = nullptr;
    if (real_d3d9 == nullptr) {
        real_d3d9 = LoadLibraryW(L"C:\\Windows\\SysWOW64\\d3d9.dll");
        if (real_d3d9 != nullptr) {
            real_create = reinterpret_cast<decltype(&Direct3DCreate9)>(
                GetProcAddress(real_d3d9, "Direct3DCreate9"));
        }
    }
    return real_create != nullptr ? real_create(sdk_version) : nullptr;
}

extern "C" __declspec(dllexport) HRESULT WINAPI Direct3DCreate9Ex(UINT sdk_version, IDirect3D9Ex** out) {
    static HMODULE real_d3d9 = nullptr;
    static decltype(&Direct3DCreate9Ex) real_create_ex = nullptr;
    if (real_d3d9 == nullptr) {
        real_d3d9 = LoadLibraryW(L"C:\\Windows\\SysWOW64\\d3d9.dll");
        if (real_d3d9 != nullptr) {
            real_create_ex = reinterpret_cast<decltype(&Direct3DCreate9Ex)>(
                GetProcAddress(real_d3d9, "Direct3DCreate9Ex"));
        }
    }
    return real_create_ex != nullptr ? real_create_ex(sdk_version, out) : E_FAIL;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(instance);
        HANDLE thread = CreateThread(nullptr, 0, camera_thread, nullptr, 0, nullptr);
        if (thread != nullptr) CloseHandle(thread);
    }
    return TRUE;
}
