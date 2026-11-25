import SwiftUI

/// A plain button that answers anywhere inside its frame.
///
/// With SwiftUI's own `.plain` style, the Mac only counts a click where the
/// label actually draws something. The tick is a hollow circle, so a click in
/// its empty middle missed the button and landed on the task behind it — and
/// opened the editor instead of ticking. The iPhone counts the whole frame,
/// which is why it only ever went wrong on the Mac.
///
/// This looks exactly like `.plain`, but makes the whole frame the button.
/// `e2e/swift_gestures.py` refuses `.plain` in the app, so it cannot creep back.
struct HitAreaButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .contentShape(Rectangle())
            .opacity(configuration.isPressed ? 0.6 : 1)
    }
}

extension ButtonStyle where Self == HitAreaButtonStyle {
    /// A plain-looking button whose whole frame takes the click, on the Mac too.
    static var hitArea: HitAreaButtonStyle { HitAreaButtonStyle() }
}
