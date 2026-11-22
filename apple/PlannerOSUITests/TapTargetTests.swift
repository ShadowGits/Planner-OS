import XCTest

/// Every tap target that sits on or beside a task, tapped for real on the
/// running app against the local API, and checked on screen and on the server.
///
/// Circles are tapped on their ring, in their hollow middle and in the margin
/// of their tap area, not only dead centre: a tap that misses a button's hit
/// area lands on the task behind it and opens the editor instead.
@MainActor
final class TapTargetTests: PlannerScreenTests {
    /// The timeline: a normal task, two side by side, a task with no time.
    private var ids: [String: String] = [:]

    override func setUpWithError() throws {
        try super.setUpWithError()
        ids["Normal row"] = try server.create("Normal row", date: today, time: "09:00", minutes: 30)
        // Same start and length: two blocks in two columns, sorted by title.
        ids["Side left"] = try server.create("Side left", date: today, time: "10:00", minutes: 60)
        ids["Side right"] = try server.create("Side right", date: today, time: "10:00", minutes: 60)
        ids["No time task"] = try server.create("No time task", date: today)
        let past = TestServer.add(today, days: -3)
        for name in ["Overdue 1", "Overdue 2", "Overdue 3"] {
            ids[name] = try server.create(name, date: past)
        }
        launch()
        XCTAssertTrue(body("Normal row").waitForExistence(timeout: 15), "the seeded day never appeared")
    }

    // MARK: Timeline

    func testTickOnNormalTaskTicksWithoutOpening() throws {
        try tickEverywhere("Normal row")
    }

    func testCornerTickOnSideBySideBlockTicksWithoutOpening() throws {
        try tickEverywhere("Side left")
        try tickEverywhere("Side right")
    }

    func testTickOnUntimedTaskTicksWithoutOpening() throws {
        launch(at: "00:00")
        try tickEverywhere("No time task")
    }

    func testTickOnShortSideBySideBlocksTicksWithoutOpening() throws {
        try server.reset()
        for name in ["Short left", "Short right"] {
            ids[name] = try server.create(name, date: today, time: "09:00", minutes: 30)
        }
        launch()
        try tickEverywhere("Short left")
        try tickEverywhere("Short right")
    }

    func testTickOnBackToBackShortTasksTicksItsOwn() throws {
        try server.reset()
        ids["First half"] = try server.create("First half", date: today, time: "09:00", minutes: 30)
        ids["Second half"] = try server.create("Second half", date: today, time: "09:30", minutes: 30)
        launch()
        try tickEverywhere("Second half")
        XCTAssertFalse(try serverDone("First half"), "a tick on the second ticked the first")
    }

    func testTickInFourNarrowColumnsTicksItsOwnTask() throws {
        try server.reset()
        let names = ["Col A", "Col B", "Col C", "Col D"]
        for name in names { ids[name] = try server.create(name, date: today, time: "09:00", minutes: 60) }
        launch()
        for name in names { try tickEverywhere(name) }
    }

    func testTappingTheTaskOpensTheEditor() throws {
        for title in ["Normal row", "Side left", "Side right"] { try opensEditor(title) }
        launch(at: "00:00")
        try opensEditor("No time task")
    }

    func testStarOnTaskStarsWithoutOpening() throws {
        try starEverywhere("Normal row")
    }

    func testStarOnSideBySideTaskStarsWithoutOpening() throws {
        try starEverywhere("Side left")
    }

    func testStarOnUntimedTaskStarsWithoutOpening() throws {
        launch(at: "00:00")
        try starEverywhere("No time task")
    }

    private func opensEditor(_ title: String) throws {
        let wasDone = try serverDone(title)
        open(title)
        XCTAssertTrue(editorButton.waitForExistence(timeout: 4), "tapping “\(title)” did not open the editor")
        closeEditor()
        XCTAssertEqual(try serverDone(title), wasDone, "opening “\(title)” changed it")
    }

    // MARK: List

    func testListViewTickStarAndOpen() throws {
        showList()
        XCTAssertTrue(app.buttons["Complete No time task"].waitForExistence(timeout: 4), "the list did not appear")
        try tickEverywhere("Normal row")
        try tickEverywhere("No time task")
        try starEverywhere("Side left")
        for title in ["Side right", "No time task"] { try opensEditor(title) }
    }

    // MARK: Focus

    func testFocusDoneTomorrowDrop() throws {
        openFocus()
        let past = TestServer.add(today, days: -3)
        let tomorrow = TestServer.add(server.calendarToday, days: 1)

        // Each on a different card, each at a different point of the button.
        try cardAction("Done", on: "Overdue 1", at: .leading)
        eventually("“Overdue 1” is done on the server") { try server.task(ids["Overdue 1"]!, on: past)?["done"] as? Bool == true }

        try cardAction("Tomorrow", on: "Overdue 2", at: .trailing)
        eventually("“Overdue 2” is on tomorrow on the server") { try server.task(ids["Overdue 2"]!, on: tomorrow) != nil }

        try cardAction("Drop", on: "Overdue 3", at: .centre, confirm: "Drop 1 task?")
        eventually("“Overdue 3” is dropped on the server") {
            try !server.inbox().contains { $0["id"] as? String == ids["Overdue 3"] }
        }
        XCTAssertFalse(editorButton.exists, "a card action opened the editor")
    }

    func testFocusPlanAllAsksFirst() throws {
        openFocus()
        let plan = app.buttons["Plan all"]
        XCTAssertTrue(plan.waitForExistence(timeout: 5))
        let question = NSPredicate(format: "(label BEGINSWITH 'Plan ' AND label CONTAINS 'over the coming days?') OR (value BEGINSWITH 'Plan ' AND value CONTAINS 'over the coming days?')")

        let before = try overdueCount()
        XCTAssertGreaterThanOrEqual(before, 3)

        // Asks, and Cancel leaves everything where it was.
        press(plan)
        XCTAssertTrue(app.staticTexts.matching(question).firstMatch.waitForExistence(timeout: 3), "Plan all did not ask first")
        cancelDialog()
        RunLoop.current.run(until: Date().addingTimeInterval(1))
        XCTAssertEqual(try overdueCount(), before, "Cancel still planned something")
        XCTAssertTrue(app.staticTexts["Overdue 1"].exists)

        // Asks again, and Plan them gives every overdue task a time.
        press(plan)
        XCTAssertTrue(app.staticTexts.matching(question).firstMatch.waitForExistence(timeout: 3))
        activate(dialogButton("Plan them"))
        XCTAssertTrue(app.staticTexts["Nothing overdue."].waitForExistence(timeout: 10), "the overdue pile is still on screen")
        eventually("nothing overdue on the server") { try overdueCount() == 0 }
    }

    // MARK: Ticks and stars, at every point

    private enum Spot: CaseIterable {
        case centre, hollow, ringRight, ringTopLeft, margin
    }

    /// Ticks, unticks, ticks… a task with a tap at each spot of its tick, and
    /// checks the screen, the server and that the editor stayed shut each time.
    private func tickEverywhere(_ title: String, file: StaticString = #filePath, line: UInt = #line) throws {
        var done = try serverDone(title)
        for spot in Spot.allCases {
            let button = app.buttons[done ? "Reopen \(title)" : "Complete \(title)"]
            XCTAssertTrue(button.waitForExistence(timeout: 4), "no tick for “\(title)”", file: file, line: line)
            let frame = button.frame
            XCTAssertGreaterThanOrEqual(frame.width, 35, "the tick on “\(title)” is \(frame.size)", file: file, line: line)
            // A half-hour task is 25 points tall, and its tick takes all of that.
            XCTAssertGreaterThanOrEqual(frame.height, 23.5, "the tick on “\(title)” is \(frame.size)", file: file, line: line)
            let circle = min(22, frame.height - 6, frame.width - 4)
            press(button, x: point(spot, in: frame.size, circle: circle).x, y: point(spot, in: frame.size, circle: circle).y)
            done.toggle()
            let after = app.buttons[done ? "Reopen \(title)" : "Complete \(title)"]
            XCTAssertTrue(after.waitForExistence(timeout: 3),
                          "tapping the tick of “\(title)” at \(spot) did not \(done ? "tick" : "untick") it", file: file, line: line)
            XCTAssertFalse(editorButton.exists, "tapping the tick of “\(title)” at \(spot) opened the editor", file: file, line: line)
            eventually("the server has “\(title)” \(done ? "done" : "open") after a tap at \(spot)", file: file, line: line) {
                try serverDone(title) == done
            }
            XCTAssertFalse(editorButton.exists, "the editor opened after ticking “\(title)” at \(spot)", file: file, line: line)
        }
    }

    private func starEverywhere(_ title: String, file: StaticString = #filePath, line: UInt = #line) throws {
        var starred = false
        for spot in [Spot.centre, .ringRight, .ringTopLeft, .margin] {
            let button = app.buttons[starred ? "Remove \(title) as Top Win" : "Choose \(title) as Top Win"]
            XCTAssertTrue(button.waitForExistence(timeout: 4), "no star for “\(title)”", file: file, line: line)
            // The star glyph is about 16 points; its edges are its ring here.
            let at = point(spot, in: button.frame.size, circle: 14)
            press(button, x: at.x, y: at.y)
            starred.toggle()
            XCTAssertTrue(app.buttons[starred ? "Remove \(title) as Top Win" : "Choose \(title) as Top Win"].waitForExistence(timeout: 3),
                          "tapping the star of “\(title)” at \(spot) did not \(starred ? "star" : "unstar") it", file: file, line: line)
            XCTAssertFalse(editorButton.exists, "tapping the star of “\(title)” at \(spot) opened the editor", file: file, line: line)
            eventually("the server has “\(title)” \(starred ? "starred" : "unstarred")", file: file, line: line) {
                try server.task(ids[title]!, on: today)?["starred"] as? Bool == starred
            }
        }
    }

    /// A spot inside a button's frame, around a circle of `circle` points at its centre.
    private func point(_ spot: Spot, in size: CGSize, circle: CGFloat) -> CGPoint {
        let c = CGPoint(x: size.width / 2, y: size.height / 2), r = circle / 2
        switch spot {
        case .centre: return c
        case .hollow: return CGPoint(x: c.x - r / 2, y: c.y + r / 2)
        case .ringRight: return CGPoint(x: c.x + r - 1, y: c.y)
        case .ringTopLeft: return CGPoint(x: c.x - (r - 1) * 0.707, y: c.y - (r - 1) * 0.707)
        // Inside the tap area, outside the circle: the corner of the frame.
        case .margin: return CGPoint(x: size.width - 6, y: size.height - 5)
        }
    }

    private func serverDone(_ title: String) throws -> Bool {
        try server.task(ids[title]!, on: today)?["done"] as? Bool ?? false
    }

    // MARK: Focus helpers

    private func openFocus() {
        activate(app.buttons["Inbox"].firstMatch)
        XCTAssertTrue(app.staticTexts["Overdue 1"].waitForExistence(timeout: 8), "the overdue cards did not appear")
    }

    private enum Edge { case leading, centre, trailing }

    /// Taps one of a card's buttons (they all share a name across cards: the
    /// one under the card's title is found by where it is).
    private func cardAction(_ name: String, on title: String, at edge: Edge, confirm: String? = nil,
                            file: StaticString = #filePath, line: UInt = #line) throws {
        let heading = app.staticTexts[title].firstMatch
        XCTAssertTrue(heading.waitForExistence(timeout: 4), "no card “\(title)”", file: file, line: line)
        let top = heading.frame
        let candidates = app.buttons.matching(NSPredicate(format: "label == %@", name)).allElementsBoundByIndex.filter {
            let f = $0.frame
            return f.minY > top.minY && f.minY < top.maxY + 140 && f.minX >= top.minX - 24 && f.minX < top.minX + 320
        }
        guard let button = candidates.min(by: { ($0.frame.minY, $0.frame.minX) < ($1.frame.minY, $1.frame.minX) }) else {
            return XCTFail("no \(name) button on “\(title)”", file: file, line: line)
        }
        let size = button.frame.size
        let spot: CGPoint
        switch edge {
        case .leading: spot = CGPoint(x: 2, y: size.height / 2)
        case .centre: spot = CGPoint(x: size.width / 2, y: size.height / 2)
        case .trailing: spot = CGPoint(x: size.width - 2, y: size.height / 2)
        }
        press(button, x: spot.x, y: spot.y)
        XCTAssertFalse(editorButton.waitForExistence(timeout: 1), "\(name) on “\(title)” opened the editor", file: file, line: line)
        if let confirm {
            XCTAssertTrue(app.staticTexts[confirm].waitForExistence(timeout: 3), "\(name) did not ask “\(confirm)”", file: file, line: line)
            activate(dialogButton(name, notAt: button.frame))
        }
        let gone = NSPredicate(format: "exists == false")
        expectation(for: gone, evaluatedWith: app.staticTexts[title], handler: nil)
        waitForExpectations(timeout: 6)
    }

    private func overdueCount() throws -> Int {
        try server.inbox().filter { $0["overdue"] as? Bool == true }.count
    }

    /// A button in a confirmation dialog, rather than one of the same name on screen behind it.
    private func dialogButton(_ name: String, notAt behind: CGRect? = nil) -> XCUIElement {
        for container in [app.sheets, app.alerts, app.dialogs, app.popovers] {
            let button = container.buttons[name]
            if button.exists { return button }
        }
        let all = app.buttons.matching(NSPredicate(format: "label == %@", name)).allElementsBoundByIndex
        return all.last { button in behind.map { button.frame != $0 } ?? true } ?? app.buttons[name]
    }

    /// Cancel where the dialog has one (the Mac); on iOS 27 the dialog is a
    /// popover without a Cancel button, and a tap outside it cancels.
    private func cancelDialog() {
        let cancel = dialogButton("Cancel")
        let region = app.otherElements["PopoverDismissRegion"].firstMatch
        if cancel.exists {
            activate(cancel)
        } else if region.exists {
            activate(region)
        } else {
            print(app.debugDescription)
            let outside = app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.97))
            #if os(macOS)
            outside.click()
            #else
            outside.tap()
            #endif
        }
        let gone = NSPredicate(format: "exists == false")
        expectation(for: gone, evaluatedWith: app.buttons["Plan them"], handler: nil)
        waitForExpectations(timeout: 4)
    }
}
