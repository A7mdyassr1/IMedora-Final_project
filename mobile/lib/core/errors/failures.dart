/// Errors the UI is allowed to show. Repositories throw these;
/// they never leak raw exceptions (HTTP, SQL...) to widgets.
class Failure implements Exception {
  const Failure(this.message);
  final String message;
  @override
  String toString() => message;
}

class AuthFailure extends Failure {
  const AuthFailure(super.message);
}

class NetworkFailure extends Failure {
  const NetworkFailure([super.message = 'Unable to reach the server.']);
}

class NotFoundFailure extends Failure {
  const NotFoundFailure([super.message = 'Not found.']);
}
