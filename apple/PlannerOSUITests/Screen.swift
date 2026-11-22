import XCTest

/// What both suites do to the running app, the same on the iPhone and the Mac.
@MainActor
class PlannerScreenTests: XCTestCase {
    let server = TestServer.shared
    var app: XCUIApplication!
    var today: String { server.calendarToday }
    func day(_ offset: Int) -> String { TestServer.add(today, days: offset) }

    override func setUpWithError() throws {
        continueAfterFailure = false
        try server.reset()
    }

    override func tearDown() {
        app?.terminate()
        super.tearDown()
    }

    /// Launches against the test server, opening at `start` today rather than now.
    func launch(at start: String? = "09:30") {
        app?.terminate()
        app = XCUIApplication()
        app.launchEnvironment["PLANNER_UI_TEST_SERVER"] = server.base
        app.launchEnvironment["PLANNER_UI_TEST_KEY"] = server.key
        if let start { app.launchEnvironment["PLANNER_UI_TEST_START"] = start }
        #if os(macOS)
        // A window saved by an earlier run would come back in its place and size.
        app.launchArguments += ["-ApplePersistenceIgnoreState", "YES"]
        #endif
        app.launch()
        XCTAssertTrue(tile.waitForExistence(timeout: 15), "the timeline never appeared")
    }

    var tile: XCUIElement { app.buttons["date-tile"].firstMatch }
    /// A task's body: the part that opens it, labelled with its title alone.
    func body(_ title: String) -> XCUIElement {
        app.buttons.matching(NSPredicate(format: "label == %@", title)).firstMatch
    }
    /// A heading on the Mac and a text on the iPhone, so found by its identifier alone.
    func header(_ date: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: "day-\(date)").firstMatch
    }
    /// The editor's Mark done or Reopen: those exact words are on no other screen.
    var editorButton: XCUIElement {
        app.buttons.matching(NSPredicate(format: "label == 'Mark done' OR label == 'Reopen'")).firstMatch
    }

    /// A tap on the iPhone, a click on the Mac. XCTest has `tap()` on the Mac
    /// too, but there it is a touchscreen's, and Mac apps ignore it.
    func activate(_ element: XCUIElement) {
        #if os(macOS)
        element.click()
        #else
        element.tap()
        #endif
    }

    func closeEditor() {
        activate(app.buttons["Cancel"].firstMatch)
        XCTAssertTrue(gone(editorButton), "the editor would not close")
    }

    func gone(_ element: XCUIElement, timeout: TimeInterval = 5) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        repeat {
            if !element.exists { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        } while Date() < deadline
        return false
    }

    func settle(_ seconds: TimeInterval = 0.8) { RunLoop.current.run(until: Date().addingTimeInterval(seconds)) }

    func point(_ element: XCUIElement, x: CGFloat, y: CGFloat) -> XCUICoordinate {
        element.coordinate(withNormalizedOffset: .zero).withOffset(CGVector(dx: x, dy: y))
    }

    /// A real touch or click at a point of an element, through hit-testing as a finger's would be.
    func press(_ element: XCUIElement, x: CGFloat? = nil, y: CGFloat? = nil,
               file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertTrue(element.waitForExistence(timeout: 5), "\(element) is not on screen", file: file, line: line)
        let size = element.frame.size
        let at = point(element, x: x ?? size.width / 2, y: y ?? size.height / 2)
        #if os(macOS)
        at.click()
        #else
        at.tap()
        #endif
    }

    /// Opens a task by its body, left of its star and tick.
    func open(_ title: String) {
        let task = body(title)
        XCTAssertTrue(task.waitForExistence(timeout: 5), "no “\(title)” on screen")
        press(task, x: min(16, task.frame.width / 3), y: min(12, task.frame.height / 2))
    }

    func swipeLeft(_ title: String) {
        let task = body(title)
        XCTAssertTrue(task.waitForExistence(timeout: 5), "no “\(title)” to swipe")
        let width = task.frame.width, y = min(12, task.frame.height / 2)
        // On the Mac a pull starts on the body, clear of the star and tick.
        let x = max(min(width * 0.55, width - 90), 20)
        let from = point(task, x: x, y: y)
        let to = from.withOffset(CGVector(dx: -min(190, task.frame.minX - app.windows.firstMatch.frame.minX + x - 4), dy: 0))
        #if os(macOS)
        from.click(forDuration: 0.02, thenDragTo: to)
        #else
        from.press(forDuration: 0.02, thenDragTo: to, withVelocity: .default, thenHoldForDuration: 0)
        #endif
        settle()
    }

    /// Holds a task near its top and drags it by `dy` points.
    func holdAndDrag(_ title: String, by dy: CGFloat, dx: CGFloat = 0, pause: TimeInterval = 0.3) {
        let task = body(title)
        XCTAssertTrue(task.waitForExistence(timeout: 5), "no “\(title)” to drag")
        let from = point(task, x: min(60, task.frame.width / 3), y: min(12, task.frame.height / 2))
        let to = from.withOffset(CGVector(dx: dx, dy: dy))
        #if os(macOS)
        from.click(forDuration: 0.7, thenDragTo: to, withVelocity: .slow, thenHoldForDuration: pause)
        #else
        from.press(forDuration: 0.7, thenDragTo: to, withVelocity: .slow, thenHoldForDuration: pause)
        #endif
        settle()
    }

    /// Scrolls the timeline: positive goes later.
    func scroll(by points: CGFloat) {
        let area = app.scrollViews["timeline"].firstMatch
        #if os(macOS)
        area.scroll(byDeltaX: 0, deltaY: -points)
        #else
        let size = area.frame.size
        // Down the hour labels, where there is no task to pick up.
        let from = point(area, x: 24, y: size.height * (points > 0 ? 0.8 : 0.2))
        let step = min(max(points, -size.height * 0.6), size.height * 0.6)
        from.press(forDuration: 0.02, thenDragTo: from.withOffset(CGVector(dx: 0, dy: -step)),
                   withVelocity: .fast, thenHoldForDuration: 0)
        #endif
        settle(0.7)
    }

    /// A button on the alert that is up, not one of the same name behind it.
    func alertButton(_ name: String) -> XCUIElement {
        let deadline = Date().addingTimeInterval(4)
        repeat {
            for container in [app.alerts, app.sheets, app.dialogs] where container.buttons[name].firstMatch.exists {
                return container.buttons[name].firstMatch
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        } while Date() < deadline
        XCTFail("no alert with a \(name) button")
        return app.buttons[name].firstMatch
    }

    func showList() {
        let named = NSPredicate(format: "label == 'More' OR title == 'More'")
        #if os(macOS)
        let more = app.menuButtons.matching(named).firstMatch
        #else
        let more = app.descendants(matching: .any).matching(named).firstMatch
        #endif
        XCTAssertTrue(more.waitForExistence(timeout: 4), "no More menu")
        activate(more)
        let item = app.buttons["Show list"].exists ? app.buttons["Show list"].firstMatch : app.menuItems["Show list"].firstMatch
        XCTAssertTrue(item.waitForExistence(timeout: 3), "More has no Show list")
        activate(item)
    }

    /// The date tile's words for a date: "Sun 22 Nov".
    func tileWords(_ date: String) -> String {
        let format = DateFormatter()
        format.locale = Locale(identifier: "en_US_POSIX")
        format.timeZone = TimeZone(identifier: "UTC")
        format.dateFormat = "yyyy-MM-dd"
        let parsed = format.date(from: date)!
        format.dateFormat = "EEE d MMM"
        return format.string(from: parsed)
    }

    func waitForTile(_ date: String, _ why: String) {
        eventually("the tile says \(tileWords(date)): \(why)") { tile.label.contains(tileWords(date)) }
    }
}
