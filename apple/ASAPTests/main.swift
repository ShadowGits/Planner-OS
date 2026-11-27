import Foundation
let changes = asapCompletionChanges(open: ["a", "b"], reminders: ["a": true, "b": false, "closed": false, "unknown": false], previouslyOpen: ["a", "b", "closed"])
precondition(changes.planner == ["a"])
precondition(changes.apple == ["closed"])
let noRead = asapCompletionChanges(open: [], reminders: ["unknown": false], previouslyOpen: [])
precondition(noRead.planner.isEmpty && noRead.apple.isEmpty)
let done = asapCompletionChanges(open: [], reminders: ["closed": true], previouslyOpen: ["closed"])
precondition(done.apple.isEmpty && done.planner.isEmpty)
print("ASAP completion reconciliation checks passed")
