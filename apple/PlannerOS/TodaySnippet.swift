import SwiftUI

/// Today as Siri shows it: a list, not a speech.
///
/// Read out, a day is a wall of words; on screen it is a glance. Every item is
/// here in time order — habits too, ticked ones too — in the timeline's own
/// colours, with what is under way and what comes next marked, and the Inbox
/// owned up to at the bottom so an empty-looking day is not mistaken for a
/// clear one.
struct TodaySnippet: View {
    /// A snippet has a fixed height to live in; past this the rest is counted.
    static let limit = 12

    let rows: [PlannerVoice.TodayRow]
    let more: Int
    let waiting: Int

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            if rows.isEmpty {
                Text("Nothing at a set time today")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            ForEach(rows) { row in
                let colour = Palette.blocks[row.palette % Palette.blocks.count]
                HStack(spacing: 10) {
                    ZStack {
                        Circle().stroke(colour, lineWidth: 2)
                        if row.state == .done {
                            Circle().fill(colour)
                            Image(systemName: "checkmark")
                                .font(.system(size: 8, weight: .bold))
                                .foregroundStyle(.white)
                        }
                    }
                    .frame(width: 16, height: 16)
                    Text(row.time)
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                        .frame(width: 62, alignment: .leading)
                    Text(row.title)
                        .font(.subheadline.weight(row.state == .now ? .semibold : .regular))
                        .strikethrough(row.state == .done)
                        .foregroundStyle(row.state == .done ? .secondary : .primary)
                        .lineLimit(1)
                    Spacer(minLength: 4)
                    switch row.state {
                    case .now: tag("Now", Palette.accent)
                    case .next: tag("Next", .secondary)
                    case .missed: tag("Missed", .orange)
                    default: EmptyView()
                    }
                }
            }
            if more > 0 {
                Text("+\(more) more").font(.caption).foregroundStyle(.secondary)
            }
            if waiting > 0 {
                Label("\(waiting) waiting in your inbox", systemImage: "tray")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.orange)
                    .padding(.top, 2)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
    }

    private func tag(_ text: String, _ colour: Color) -> some View {
        Text(text)
            .font(.caption2.weight(.bold))
            .foregroundStyle(colour)
    }
}
