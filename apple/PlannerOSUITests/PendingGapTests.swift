import XCTest

@MainActor
final class PendingGapTests: XCTestCase {
    private let server = TestServer.shared
    private var app: XCUIApplication!
    private var oldID = ""
    private var longID = ""
    private var past: String { TestServer.add(server.today, days: -2) }

    override func setUpWithError() throws {
        continueAfterFailure = false
        try server.reset()
        try server.create("Before the gap", date: server.today, time: "09:00", minutes: 30)
        try server.create("After the gap", date: server.today, time: "10:30", minutes: 30)
        oldID = try server.create("Finish previous proposal", date: past, time: "14:00", minutes: 45)
        try server.send("PATCH", "/v2/day/tasks/\(oldID)", ["notes": "Keep the original notes"])
        longID = try server.create("Long previous task", date: past, minutes: 90)
        let completed = try server.create("Already finished", date: past, minutes: 20)
        try server.send("PATCH", "/v2/day/tasks/\(completed)", ["done": true])
        app = XCUIApplication()
        app.launchEnvironment["PLANNER_UI_TEST_SERVER"] = server.base
        app.launchEnvironment["PLANNER_UI_TEST_KEY"] = server.key
        app.launch()
        XCTAssertTrue(app.staticTexts["Before the gap"].waitForExistence(timeout: 15))
    }

    override func tearDown() {
        app?.terminate()
        super.tearDown()
    }

    private func press(_ element: XCUIElement) {
        XCTAssertTrue(element.waitForExistence(timeout: 5), app.debugDescription)
        #if os(macOS)
        element.click()
        #else
        element.tap()
        #endif
    }

    private func openPicker() {
        // Tap the actual free-time suggestion, exercising its hit target.
        let suggestion = app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@ OR value CONTAINS %@", "Anything you'd like", "Anything you'd like")).firstMatch
        press(suggestion)
        press(app.buttons["fit-previous-pending"])
        XCTAssertTrue(app.buttons["pending-task-\(oldID)"].waitForExistence(timeout: 8), app.debugDescription)
    }

    private func screenshot(_ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    func testFitMovesExistingTaskAndPreservesDetails() throws {
        openPicker()
        let card = app.buttons["pending-task-\(oldID)"]
        // macOS exposes a card's text as the button label; iOS also exposes
        // its individual text elements.
        XCTAssertTrue(card.label.contains("Planned") || app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@ OR value CONTAINS %@", "Planned", "Planned")).firstMatch.exists)
        XCTAssertTrue(card.label.contains("45 min") || app.staticTexts["45 min"].exists)
        XCTAssertFalse(app.staticTexts["Already finished"].exists)
        XCTAssertFalse(app.buttons["pending-task-\(longID)"].isEnabled)
        screenshot("Pending tasks in the selected gap")
        press(app.buttons["pending-task-\(oldID)"])
        eventually("the same task moved into 09:30") {
            let task = try server.task(oldID, on: server.today)
            return (task?["start_time"] as? String)?.hasPrefix("09:30") == true
        }
        let moved = try XCTUnwrap(server.task(oldID, on: server.today))
        XCTAssertEqual(moved["estimated_minutes"] as? Int, 45)
        XCTAssertEqual(moved["notes"] as? String, "Keep the original notes")
        XCTAssertEqual(moved["done"] as? Bool, false)
        XCTAssertNil(try server.task(oldID, on: past))
        XCTAssertEqual(try server.day(server.today).filter { $0["title"] as? String == "Finish previous proposal" }.count, 1)
        eventually("picker closes after saving") { !app.buttons["pending-task-\(oldID)"].exists }
        XCTAssertTrue(app.staticTexts["Finish previous proposal"].waitForExistence(timeout: 5))
        screenshot("Previous task fitted on the timeline")
    }

    func testSearchAndCancelDoNotMoveAnything() throws {
        openPicker()
        let search = app.textFields["pending-task-search"]
        press(search)
        search.typeText("No matching task")
        XCTAssertTrue(app.staticTexts["No tasks match your search."].waitForExistence(timeout: 3))
        XCTAssertEqual((try server.task(oldID, on: past)?["start_time"] as? String)?.prefix(5), "14:00")
        press(app.buttons["Cancel"].firstMatch)
        eventually("cancel closes the picker") { !app.textFields["pending-task-search"].exists }
        XCTAssertNil(try server.task(oldID, on: server.today))
    }

    func testNewBookingKeepsPickerOpenWithoutMovingTask() throws {
        openPicker()
        try server.create("Booked elsewhere", date: server.today, time: "09:45", minutes: 30)
        press(app.buttons["pending-task-\(oldID)"])
        XCTAssertTrue(app.staticTexts["pending-task-error"].waitForExistence(timeout: 8))
        XCTAssertTrue(app.buttons["pending-task-\(oldID)"].exists)
        XCTAssertNotNil(try server.task(oldID, on: past))
        XCTAssertNil(try server.task(oldID, on: server.today))
        screenshot("Changed gap leaves task unchanged")
    }

    func testCompletedElsewhereCannotBeFitted() throws {
        openPicker()
        try server.send("PATCH", "/v2/day/tasks/\(oldID)", ["done": true])
        press(app.buttons["pending-task-\(oldID)"])
        XCTAssertTrue(app.staticTexts["pending-task-error"].waitForExistence(timeout: 8))
        XCTAssertEqual(try server.task(oldID, on: past)?["done"] as? Bool, true)
        XCTAssertNil(try server.task(oldID, on: server.today))
    }

    func testAddingANewTaskFromTheGapStillWorks() throws {
        let suggestion = app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@ OR value CONTAINS %@", "Anything you'd like", "Anything you'd like")).firstMatch
        press(suggestion)
        // On Mac the form's title is a separate static label rather than
        // the text field's accessibility label. This is the first form field.
        let title = app.textFields.firstMatch
        press(title)
        title.typeText("A new task in the gap")
        press(app.buttons["Add"].firstMatch)
        eventually("a new task saves at the chosen gap") {
            try server.day(server.today).contains {
                $0["title"] as? String == "A new task in the gap" && ($0["start_time"] as? String)?.hasPrefix("09:30") == true
            }
        }
        XCTAssertNotNil(try server.task(oldID, on: past))
    }
}
