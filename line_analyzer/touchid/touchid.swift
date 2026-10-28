// 指紋認証（Touch ID）を求める小さな部品。成功したら 0、だめなら 1 で終わる。
// Touch ID が使えないときは、Macのログインパスワードでの認証になる。
import Foundation
import LocalAuthentication

let reason = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "ふたりの記録帳を開きます"
let context = LAContext()
var error: NSError?
guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else {
    FileHandle.standardError.write("認証を使えません: \(error?.localizedDescription ?? "")\n".data(using: .utf8)!)
    exit(1)
}
let done = DispatchSemaphore(value: 0)
var ok = false
context.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: reason) { success, _ in
    ok = success
    done.signal()
}
done.wait()
exit(ok ? 0 : 1)
