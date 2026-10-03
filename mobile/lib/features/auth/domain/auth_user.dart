/// Mirrors the IMedora `users` table (+ names resolved by the backend).
/// `role` matches `roles.name`: admin / biomedical_engineer /
/// technician / department_user.
class AuthUser {
  const AuthUser({
    required this.id,
    required this.fullName,
    required this.email,
    required this.hospitalName,
    required this.departmentName,
    required this.role,
  });

  final String id;
  final String fullName;
  final String email;
  final String hospitalName;
  final String departmentName;
  final String role;
}

class AuthSession {
  const AuthSession({required this.user, required this.token});
  final AuthUser user;
  final String token;
}
