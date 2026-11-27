import Foundation

/// Completion wins; an unknown reminder is never treated as a deleted task.
func asapCompletionChanges(open: Set<String>, reminders: [String: Bool], previouslyOpen: Set<String>) -> (planner: Set<String>, apple: Set<String>) {
    let planner = Set(reminders.filter { open.contains($0.key) && $0.value }.keys)
    let apple = Set(reminders.filter { !open.contains($0.key) && previouslyOpen.contains($0.key) && !$0.value }.keys)
    return (planner, apple)
}
